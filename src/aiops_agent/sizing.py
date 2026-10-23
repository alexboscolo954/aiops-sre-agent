"""Sizings (slices 9.2, 9.3): the requests each Workload container should have, read-only.

A pure function of one container's pooled usage (usage.py), the time and its Sizing
policy (contracts.py; the numbers below are `production`'s):

- CPU: the 95th percentile, recent samples weighted more (half-life 24 h, like VPA),
  plus 15% headroom. A container that is throttled hides its real demand, so its CPU
  is never lowered while it is.
- Memory: the peak over the window, plus 20%. Weighting can't move a maximum: memory
  follows a drop only once the old peak leaves the window. After an OOM kill the peak
  is the limit, not the demand, so memory is never lowered then.
- Then the floors, then the policy's max (if any), then the limit: limits are kept, a
  request never goes above one, and a cap or a limit below what the container needs
  is flagged as risk. Then rounding up to a millicore or a MiB.
- A request changes only when the difference is at least 10% and at least 10m CPU or
  16 MiB; a container without one always gets one.
- Under 24 hours of history a container is still learning and gets no Sizing.

Each risk has a kind, for counting and ranking (slice 9.4). Waste is the request
above the Sizing, times the average pods over the container's history. Each week the
Operator gets a digest of it (slice 9.5b).
"""

import asyncio
import bisect
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, NamedTuple

from aiops_agent import usage
from aiops_agent.contracts import BUILTIN, Contract, Policy
from aiops_agent.slack import clean
from aiops_agent.usage import ContainerUsage, Workload

if TYPE_CHECKING:
    from aiops_agent.store import Store

PRODUCTION = BUILTIN["production"]
HALF_LIFE_S = PRODUCTION.half_life
MIN_CHANGE = {"cpu": 0.010, "memory": 16 * 2**20}
THROTTLED = 0.10  # share of CFS periods throttled above which CPU demand is hidden

Action = Literal["set", "raise", "lower", "keep"]
RiskKind = Literal[
    "oom_killed",
    "throttled",
    "under_requested",
    "limit_below_need",
    "capped_by_policy",
    "request_unset",
]
DERIVED = ("under_requested", "request_unset")  # the action says it: `sizing show` omits them


class Risk(NamedTuple):
    kind: RiskKind
    text: str


@dataclass
class Resource:
    current: float | None  # the request now: cores or bytes, None when unset
    target: float  # what the request should be (current when kept)
    action: Action
    basis: float  # the usage figure it came from: CPU p95 or memory peak


@dataclass
class Sizing:
    workload: Workload
    container: str
    state: Literal["ready", "learning"]
    history_s: float  # oldest to newest pooled sample
    cpu: Resource | None = None
    memory: Resource | None = None
    risks: list[Risk] = field(default_factory=list)


def weighted_percentile(
    samples: list[tuple[float, float]], q: float, now: float, half_life_s: float = HALF_LIFE_S
) -> float:
    """The q-th percentile of the values, each weighted 0.5 ** (age / half-life). With
    equal ages it is the nearest-rank percentile."""
    ordered = sorted((v, 0.5 ** (max(0.0, now - t) / half_life_s)) for t, v in samples)
    total = sum(w for _, w in ordered)
    running = 0.0
    for v, w in ordered:
        running += w
        if running >= q * total - 1e-12 * total:
            return v
    return ordered[-1][0]


def _round_up(resource: str, value: float) -> float:
    if resource == "cpu":
        return math.ceil(round(value * 1000, 6)) / 1000
    return float(math.ceil(round(value / 2**20, 6)) * 2**20)


def show(resource: str, value: float) -> str:
    return f"{value * 1000:.0f}m" if resource == "cpu" else f"{value / 2**20:.0f}Mi"


def _resource(
    resource: str,
    basis: float,
    u: ContainerUsage,
    risks: list[Risk],
    hold: Risk | None,
    policy: Policy,
) -> Resource:
    """headroom, floor, max, limit, rounding, then the change threshold. `hold`: why
    this resource may not be lowered (its usage hides the real demand)."""
    p = policy.cpu if resource == "cpu" else policy.memory
    target = max(basis * (1 + p.headroom), p.floor)
    if p.max is not None and target > p.max:
        risks.append(
            Risk(
                "capped_by_policy",
                f"{resource} capped at {show(resource, p.max)} by the policy: it needs "
                f"{show(resource, _round_up(resource, target))}",
            )
        )
        target = p.max
    limit = u.limits.get(resource)
    if limit is not None and target > limit:
        risks.append(
            Risk(
                "limit_below_need",
                f"{resource} limit {show(resource, limit)} is below the "
                f"{show(resource, _round_up(resource, target))} it needs",
            )
        )
        target = limit
    target = _round_up(resource, target)
    current = u.requests.get(resource)
    if current is None:
        return Resource(None, target, "set", basis)
    if abs(target - current) < max(policy.threshold * current, MIN_CHANGE[resource]):
        return Resource(current, current, "keep", basis)
    if target < current and hold:
        risks.append(hold)
        return Resource(current, current, "keep", basis)
    return Resource(current, target, "raise" if target > current else "lower", basis)


def size(u: ContainerUsage, now: float, policy: Policy = PRODUCTION) -> Sizing:
    """The Sizing for one container, or `learning` under the policy's history."""
    times = [t for t, _ in u.cpu + u.memory]
    history = max(times) - min(times) if times else 0.0
    s = Sizing(u.workload, u.container, "learning", history)
    if history < policy.history:
        return s
    s.state = "ready"
    throttled = u.throttled is not None and u.throttled > THROTTLED
    if throttled:
        assert u.throttled is not None
        s.risks.append(
            Risk(
                "throttled",
                f"throttled {u.throttled:.0%} of CPU periods: its real CPU demand is higher",
            )
        )
    if u.cpu:
        hold = (
            Risk("throttled", "CPU kept: throttling hides how much it needs") if throttled else None
        )
        basis = weighted_percentile(u.cpu, policy.cpu.percentile, now, policy.half_life)
        s.cpu = _resource("cpu", basis, u, s.risks, hold, policy)
    if u.memory:
        hold = None
        if u.oom_killed_pods:
            s.risks.append(
                Risk(
                    "oom_killed",
                    f"OOM-killed in {u.oom_killed_pods} pods: its peak is its limit, "
                    "not its demand",
                )
            )
            hold = Risk("oom_killed", "memory kept: OOM kills hide how much it needs")
        peak = max(v for _, v in u.memory)
        s.memory = _resource("memory", peak, u, s.risks, hold, policy)
    return s


def pod_times(u: ContainerUsage) -> list[float]:
    """A time per pod per step: Running pods from kube-state-metrics, else (no phase
    series) its CPU samples, which outlive a pod by `rate`'s 5 minutes."""
    return u.running or [t for t, _ in u.cpu or u.memory]


def avg_pods(u: ContainerUsage, seen: list[float]) -> float:
    """Pods per step from the container's first pod time to its last, over the steps
    its cluster has any (`seen`, sorted): a CronJob that runs an hour a day averages a
    twenty-fourth of its pods, as its requests reserve, and a gap in Prometheus (a
    scrape missed by every pod) counts for no one."""
    times = pod_times(u)
    if not times:
        return 0.0
    steps = bisect.bisect_right(seen, max(times)) - bisect.bisect_left(seen, min(times))
    return len(times) / steps


def rows(
    c: Contract, by_window: dict[int, list[tuple[str, ContainerUsage]]], now: float
) -> list[dict[str, Any]]:
    """Every container's Sizing under its policy, as `sizing show`, the stored runs and
    `sizing waste` see it, sorted by name. `off` gives an excluded row."""
    out: dict[str, dict[str, Any]] = {}
    for window, found in by_window.items():
        seen: dict[str, set[float]] = {}
        for cluster, u in found:
            seen.setdefault(cluster, set()).update(pod_times(u))
        steps = {cluster: sorted(times) for cluster, times in seen.items()}
        for cluster, u in found:
            w = u.workload
            row: dict[str, Any] = {
                "workload": f"{cluster}/{w.namespace}/{w.kind}/{w.name}/{u.container}",
                "cluster": cluster,
                "namespace": w.namespace,
                "kind": w.kind,
                "name": w.name,
                "container": u.container,
                "policy": c.sizing.policy_for(cluster, w.namespace, w.kind, w.name, u.container),
            }
            policy = c.sizing.policy(row["policy"])
            if policy is None:
                out[row["workload"]] = {**row, "state": "excluded"}
                continue
            if policy.window != window:
                continue
            s = size(u, now, policy)
            pods = avg_pods(u, steps[cluster])
            row |= {
                "state": s.state,
                "history_h": round(s.history_s / 3600, 1),
                "needs_h": round(policy.history / 3600, 1),
                "window_h": round(window / 3600, 1),
                "pods": round(pods, 1),
            }
            risks = list(s.risks)
            waste = {}
            for name, res in (("cpu", s.cpu), ("memory", s.memory)):
                if res is None:
                    continue
                row[name] = {
                    "action": res.action,
                    "current": res.current,
                    "target": res.target,
                    "basis": res.basis,
                    "limit": u.limits.get(name),  # None: no limit (stored since 9.6)
                }
                if res.action == "set":
                    risks.append(Risk("request_unset", f"{name} has no request"))
                if res.action == "raise" and res.current is not None:
                    risks.append(
                        Risk(
                            "under_requested",
                            f"{name} request {show(name, res.current)} is below the "
                            f"{show(name, res.target)} it needs",
                        )
                    )
                current = res.current or 0.0
                waste[name] = max(0.0, current - res.target) * pods
            if s.state == "ready":
                row["waste"] = waste
            row["risks"] = [r._asdict() for r in risks]
            out[row["workload"]] = row
    return [out[k] for k in sorted(out)]


def rank(workload: dict[str, Any]) -> float:
    """A Workload's waste as one number to sort by."""
    # ponytail: a core weighs as much as 4 GiB (a common node shape) until Phase 10
    # prices each Contract's cores and GiB
    return float(workload["waste"]["cpu"] + workload["waste"]["memory"] / 2**30 / 4)


def report(rows: list[dict[str, Any]], clusters: dict[str, Any]) -> dict[str, Any]:
    """Stored rows (one per container) as Workloads ranked by waste, each with its
    containers and risks, plus the total, the learning and excluded rows and each
    cluster's status: what `sizing waste` and the console show."""
    workloads: dict[str, dict[str, Any]] = {}
    learning: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for r in rows:
        if r["state"] != "ready":
            (learning if r["state"] == "learning" else excluded).append(r)
            continue
        w = workloads.setdefault(
            r["workload"].rsplit("/", 1)[0],
            {
                "workload": r["workload"].rsplit("/", 1)[0],
                **{k: r[k] for k in ("cluster", "namespace", "kind", "name")},
                "pods": 0.0,
                "waste": {"cpu": 0.0, "memory": 0.0},
                "risks": [],
                "containers": [],
            },
        )
        w["pods"] = max(w["pods"], r["pods"])
        for res in ("cpu", "memory"):
            w["waste"][res] += r["waste"].get(res, 0.0)
        w["risks"] += [{**risk, "container": r["container"]} for risk in r["risks"]]
        w["containers"].append(r)
    ranked = sorted(workloads.values(), key=lambda w: (-rank(w), w["workload"]))
    return {
        "clusters": clusters,
        "total": {res: sum(w["waste"][res] for w in ranked) for res in ("cpu", "memory")},
        "workloads": ranked,
        "learning": learning,
        "excluded": excluded,
    }


HOURLY = 3600.0  # seconds between a Contract's stored Sizing runs


async def store_run(
    store: "Store", c: Contract, at: float, every: float = HOURLY
) -> usage.Collected | None:
    """Size every container of the Contract as of `at` and store the run, unless one
    started less than `every` seconds before; then prune old runs. What was read, or
    None when not due. A Contract without a Prometheus has nothing to run."""
    if not usage.targets(c):
        return None
    run_id = await store.claim_sizing_run(c.id, at, every)
    if run_id is None:
        return None
    found = await asyncio.to_thread(usage.collect, c, c.sizing.windows(), at)
    await store.finish_sizing_run(run_id, c.id, found.clusters, rows(c, found.by_window, at))
    await store.prune_sizings(c.id, at)
    return found


WEEK = 7 * 86400.0
TOP = 5  # Workloads named in the digest


def utc(at: float | None) -> str:
    return "never" if at is None else datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%d %H:%M UTC")


def _kinds(report: dict[str, Any]) -> dict[str, set[str]]:
    return {w["workload"]: {r["kind"] for r in w["risks"]} for w in report["workloads"]}


def digest_text(
    contract_id: str, now: dict[str, Any], week: dict[str, Any], link: str | None = None
) -> str:
    """The weekly digest (Slack mrkdwn) from report() now and as of a week ago: total
    waste and its change, the top Workloads by waste, risk kinds a Workload didn't have
    a week ago, stale clusters, the containers still learning, then the link."""
    total = now["total"]
    lines = [f"*Weekly Sizing digest: {contract_id}*"]
    if not now["clusters"]:
        lines.append("No Sizings stored yet.")
    else:
        waste = f"Waste: {total['cpu']:.2f} cores, {total['memory'] / 2**30:.2f} GiB"
        compared = any(st["at"] is not None for st in week["clusters"].values())
        if compared:
            then = week["total"]
            waste += (
                f" ({total['cpu'] - then['cpu']:+.2f} cores, "
                f"{(total['memory'] - then['memory']) / 2**30:+.2f} GiB vs 7 days ago)"
            )
        else:
            waste += " (no Sizings from 7 days ago to compare)"
        lines.append(waste)
        top = [w for w in now["workloads"] if rank(w) > 0][:TOP]
        if top:
            lines.append("*Top Workloads by waste*")
            lines += [
                f"{i}. `{w['workload']}`: {w['waste']['cpu']:.2f} cores, "
                f"{w['waste']['memory'] / 2**30:.2f} GiB"
                for i, w in enumerate(top, 1)
            ]
        before = _kinds(week)
        new = {
            name: sorted(kinds - before.get(name, set()) if compared else kinds)
            for name, kinds in _kinds(now).items()
        }
        risky = [f"• `{name}`: {', '.join(k)}" for name, k in new.items() if k]
        if risky:
            lines.append("*New risks since last week*" if compared else "*Risks*")
            lines += risky
        stale = [
            f"• {cluster}: stale since {utc(st['since'])}: {st['error']}"
            if st["error"]
            else f"• {cluster}: never read"
            for cluster, st in sorted(now["clusters"].items())
            if st["error"] or st["at"] is None
        ]
        if stale:
            lines += ["*Stale clusters*", *stale]
        if now["learning"]:
            lines.append(f"Containers still learning: {len(now['learning'])}.")
    text = clean("\n".join(lines))
    return f"{text}\n<{link}|Open the Workloads page>" if link else text


async def digest(store: "Store", c: Contract, at: float, console_url: str | None) -> str:
    """The Contract's digest as of `at`, from its stored Sizings (as `sizing waste`)."""
    clusters = {t.cluster for t in usage.targets(c)}
    now = report(*await store.latest_sizings(c.id, clusters, before=at))
    week = report(*await store.latest_sizings(c.id, clusters, before=at - WEEK))
    link = f"{console_url.rstrip('/')}/app/?contract={c.id}" if console_url else None
    return digest_text(c.id, now, week, link)
