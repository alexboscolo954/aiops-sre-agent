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
above the Sizing, times the average pods over the container's history.
"""

import asyncio
import bisect
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, NamedTuple

from aiops_agent import usage
from aiops_agent.contracts import BUILTIN, Contract, Policy
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


def avg_pods(u: ContainerUsage, seen: list[float]) -> float:
    """Pods per step from the container's first sample to its last, over the steps its
    cluster has any sample (`seen`, sorted): a CronJob that runs an hour a day averages
    a twenty-fourth of its pods, as its requests reserve, and a gap in Prometheus
    (a scrape missed by every pod) counts for no one."""
    times = [t for t, _ in u.cpu or u.memory]
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
            seen.setdefault(cluster, set()).update(t for t, _ in u.cpu or u.memory)
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
