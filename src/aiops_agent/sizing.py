"""Sizings (slice 9.2): the requests each Workload container should have, read-only.

A pure function of one container's pooled usage (usage.py) and the time:

- CPU: the 95th percentile, recent samples weighted more (half-life 24 h, like VPA),
  plus 15% headroom. A container that is throttled hides its real demand, so its CPU
  is never lowered while it is.
- Memory: the peak over the window, plus 20%. Weighting can't move a maximum: memory
  follows a drop only once the old peak leaves the window. After an OOM kill the peak
  is the limit, not the demand, so memory is never lowered then.
- Then the floors, then the limit: limits are kept, a request never goes above one,
  and a limit below what the container needs is flagged as risk. Then rounding up to a
  millicore or a MiB.
- A request changes only when the difference is at least 10% and at least 10m CPU or
  16 MiB; a container without one always gets one.
- Under 24 hours of history a container is still learning and gets no Sizing.
"""

import math
from dataclasses import dataclass, field
from typing import Literal

from aiops_agent.usage import ContainerUsage, Workload

HALF_LIFE_S = 24 * 3600
MIN_HISTORY_S = 24 * 3600
CPU_PERCENTILE = 0.95
HEADROOM = {"cpu": 0.15, "memory": 0.20}
FLOOR = {"cpu": 0.010, "memory": 32 * 2**20}  # cores, bytes
THRESHOLD = 0.10  # relative change below which a request is kept
MIN_CHANGE = {"cpu": 0.010, "memory": 16 * 2**20}
THROTTLED = 0.10  # share of CFS periods throttled above which CPU demand is hidden

Action = Literal["set", "raise", "lower", "keep"]


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
    risks: list[str] = field(default_factory=list)


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
    resource: str, basis: float, u: ContainerUsage, risks: list[str], hold: str | None
) -> Resource:
    """headroom, floor, limit, rounding, then the change threshold. `hold`: why this
    resource may not be lowered (its usage hides the real demand)."""
    target = max(basis * (1 + HEADROOM[resource]), FLOOR[resource])
    limit = u.limits.get(resource)
    if limit is not None and target > limit:
        risks.append(
            f"{resource} limit {show(resource, limit)} is below the "
            f"{show(resource, _round_up(resource, target))} it needs"
        )
        target = limit
    target = _round_up(resource, target)
    current = u.requests.get(resource)
    if current is None:
        return Resource(None, target, "set", basis)
    if abs(target - current) < max(THRESHOLD * current, MIN_CHANGE[resource]):
        return Resource(current, current, "keep", basis)
    if target < current and hold:
        risks.append(hold)
        return Resource(current, current, "keep", basis)
    return Resource(current, target, "raise" if target > current else "lower", basis)


def size(u: ContainerUsage, now: float) -> Sizing:
    """The Sizing for one container, or `learning` under MIN_HISTORY_S of usage."""
    times = [t for t, _ in u.cpu + u.memory]
    history = max(times) - min(times) if times else 0.0
    s = Sizing(u.workload, u.container, "learning", history)
    if history < MIN_HISTORY_S:
        return s
    s.state = "ready"
    throttled = u.throttled is not None and u.throttled > THROTTLED
    if throttled:
        assert u.throttled is not None
        s.risks.append(f"throttled {u.throttled:.0%} of CPU periods: its real CPU demand is higher")
    if u.cpu:
        hold = "CPU kept: throttling hides how much it needs" if throttled else None
        s.cpu = _resource("cpu", weighted_percentile(u.cpu, CPU_PERCENTILE, now), u, s.risks, hold)
    if u.memory:
        hold = None
        if u.oom_killed_pods:
            s.risks.append(
                f"OOM-killed in {u.oom_killed_pods} pods: its peak is its limit, not its demand"
            )
            hold = "memory kept: OOM kills hide how much it needs"
        peak = max(v for _, v in u.memory)
        s.memory = _resource("memory", peak, u, s.risks, hold)
    return s
