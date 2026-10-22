"""Sizings (slice 9.2): percentiles, decay, headroom, floors, limits, thresholds, holds."""

import math

import pytest

from aiops_agent import sizing
from aiops_agent.sizing import weighted_percentile
from aiops_agent.usage import ContainerUsage, Workload

H = 3600
DAY = 24 * H
NOW = 10 * DAY
MI = 2**20
WEB = Workload("shop", "Deployment", "web")


def series(values: list[float], hours: float = 48, end: float = NOW) -> list[tuple[float, float]]:
    """values spread evenly over the last `hours`, oldest first."""
    n = len(values)
    return [(end - hours * H + i * hours * H / max(1, n - 1), v) for i, v in enumerate(values)]


def usage(
    cpu: list[float] | None = None,
    memory: list[float] | None = None,
    requests: dict[str, float] | None = None,
    limits: dict[str, float] | None = None,
    hours: float = 48,
    **kw: object,
) -> ContainerUsage:
    u = ContainerUsage(WEB, "app")
    u.cpu = series(cpu or [], hours)
    u.memory = series(memory or [], hours)
    u.requests = requests if requests is not None else {"cpu": 1.0, "memory": 1024 * MI}
    u.limits = limits or {}
    for k, v in kw.items():
        setattr(u, k, v)
    return u


# --- weighted percentile -------------------------------------------------------------


@pytest.mark.parametrize("n", [1, 7, 20, 101])
@pytest.mark.parametrize("q", [0.5, 0.9, 0.95, 0.99, 1.0])
def test_equal_weights_give_the_nearest_rank_percentile(n: int, q: float) -> None:
    values = [float((i * 37) % n) for i in range(n)]
    same_time = [(NOW, v) for v in values]
    expected = sorted(values)[max(0, math.ceil(q * n) - 1)]
    assert weighted_percentile(same_time, q, NOW) == expected


def test_old_samples_count_less() -> None:
    old_high = [(NOW - 5 * DAY, 10.0)] * 50
    recent_low = [(NOW - H, 1.0)] * 50
    assert weighted_percentile(old_high + recent_low, 0.95, NOW) == 1.0
    assert weighted_percentile(old_high + recent_low, 0.95, NOW, half_life_s=10 * DAY) == 10.0


def test_a_drop_is_followed_in_about_four_days_a_rise_within_hours() -> None:
    """Slow to cut, quick to grow. After usage halves, the old level weighs 0.5 ** days
    of the total, so the p95 moves once that is under 5%: about 4.3 days. A rise is
    above the p95 as soon as it carries 5% of the weight."""

    def steady(
        level: float, start_days_ago: float, end_days_ago: float
    ) -> list[tuple[float, float]]:
        n = int((start_days_ago - end_days_ago) * 144)
        return [(NOW - start_days_ago * DAY + i * 600, level) for i in range(n)]

    def p95_after(days: float, before: float, after: float) -> float:
        samples = steady(before, 7, days) + steady(after, days, 0)
        return weighted_percentile(samples, 0.95, NOW)

    assert p95_after(4.0, 1.0, 0.5) == 1.0
    assert p95_after(4.5, 1.0, 0.5) == 0.5
    assert p95_after(3 / 24, 0.5, 1.0) == 1.0  # three hours


# --- learning ------------------------------------------------------------------------


def test_under_a_day_of_history_it_is_still_learning() -> None:
    s = sizing.size(usage(cpu=[0.1] * 10, memory=[50 * MI] * 10, hours=23.9), NOW)
    assert s.state == "learning" and s.cpu is None and s.memory is None


def test_a_day_of_history_is_enough() -> None:
    s = sizing.size(usage(cpu=[0.1] * 10, memory=[50 * MI] * 10, hours=24), NOW)
    assert s.state == "ready" and s.history_s == DAY


def test_history_spans_cpu_and_memory_samples_together() -> None:
    u = usage(cpu=[0.1] * 3, hours=10)
    u.memory = [(NOW - 30 * H, 50 * MI)]
    assert sizing.size(u, NOW).history_s == 30 * H


# --- the numbers ---------------------------------------------------------------------


def test_an_over_requested_workload_is_lowered_to_p95_plus_headroom() -> None:
    """The lab's api: asks 1 CPU and 1 GiB, uses about 0.1 core and 80 MiB."""
    s = sizing.size(usage(cpu=[0.09, 0.1, 0.1, 0.11] * 25, memory=[75 * MI, 80 * MI] * 50), NOW)
    assert s.cpu and s.cpu.action == "lower" and s.cpu.basis == 0.11
    assert s.cpu.target == pytest.approx(0.127)  # 0.11 * 1.15, up to a millicore
    assert s.memory and s.memory.action == "lower" and s.memory.target == 96 * MI  # 80 * 1.2
    assert s.risks == []


def test_floors_apply_before_the_limit() -> None:
    s = sizing.size(usage(cpu=[0.001] * 50, memory=[1 * MI] * 50, requests={}), NOW)
    assert s.cpu and s.cpu.target == 0.010 and s.cpu.action == "set"
    assert s.memory and s.memory.target == 32 * MI


def test_rounding_is_up_to_a_millicore_and_a_mib() -> None:
    s = sizing.size(usage(cpu=[0.2001] * 50, memory=[(100 + 1 / 3) * MI] * 50, requests={}), NOW)
    assert s.cpu and s.cpu.target == 0.231  # 0.230115 up
    assert s.memory and s.memory.target == 121 * MI  # 120.4 up


def test_a_request_never_goes_above_its_limit_and_the_conflict_is_flagged() -> None:
    s = sizing.size(
        usage(
            cpu=[0.3] * 50,
            memory=[300 * MI] * 50,
            requests={},
            limits={"cpu": 0.2, "memory": 256 * MI},
        ),
        NOW,
    )
    assert s.cpu and s.cpu.target == 0.2
    assert s.memory and s.memory.target == 256 * MI
    assert "cpu limit 200m is below the 345m it needs" in s.risks
    assert "memory limit 256Mi is below the 360Mi it needs" in s.risks


def test_a_container_without_a_request_always_gets_one() -> None:
    s = sizing.size(usage(cpu=[0.1] * 50, memory=[50 * MI] * 50, requests={}), NOW)
    assert s.cpu and (s.cpu.current, s.cpu.action) == (None, "set")
    assert s.memory and s.memory.action == "set"


@pytest.mark.parametrize(
    ("current", "used", "action"),
    [
        (0.500, 0.500 / 1.15 * 0.95, "keep"),  # target 5% under: kept
        (0.500, 0.500 / 1.15 * 0.85, "lower"),  # 15% under
        (0.500, 0.500 / 1.15 * 1.15, "raise"),  # 15% over
        (0.050, 0.050 / 1.15 * 0.85, "keep"),  # 15% but under 10m
    ],
)
def test_cpu_changes_only_past_both_thresholds(current: float, used: float, action: str) -> None:
    s = sizing.size(usage(cpu=[used] * 50, requests={"cpu": current}), NOW)
    assert s.cpu and s.cpu.action == action
    if action == "keep":
        assert s.cpu.target == current


@pytest.mark.parametrize(
    ("current_mib", "peak_mib", "action"),
    [
        (100, 100 / 1.2 * 0.95, "keep"),  # 5% under
        (200, 200 / 1.2 * 0.85, "lower"),  # 30 MiB under
        (100, 100 / 1.2 * 0.88, "keep"),  # 12% but 12 MiB: under 16 MiB
    ],
)
def test_memory_changes_only_past_both_thresholds(
    current_mib: float, peak_mib: float, action: str
) -> None:
    s = sizing.size(usage(memory=[peak_mib * MI] * 50, requests={"memory": current_mib * MI}), NOW)
    assert s.memory and s.memory.action == action


def test_memory_follows_the_peak_not_a_percentile() -> None:
    s = sizing.size(usage(memory=[50 * MI] * 99 + [200 * MI], requests={}), NOW)
    assert s.memory and s.memory.basis == 200 * MI and s.memory.target == 240 * MI


def test_no_cpu_samples_no_cpu_sizing() -> None:
    s = sizing.size(usage(memory=[50 * MI] * 50), NOW)
    assert s.cpu is None and s.memory is not None


# --- usage that hides demand ---------------------------------------------------------


def test_a_throttled_container_is_never_lowered() -> None:
    """The lab's throttled: wants 0.5 cores, a 200m limit holds it at about 0.17."""
    u = usage(cpu=[0.167] * 50, requests={"cpu": 1.0}, limits={"cpu": 0.2}, throttled=0.64)
    s = sizing.size(u, NOW)
    assert s.cpu and s.cpu.action == "keep" and s.cpu.target == 1.0
    assert "throttled 64% of CPU periods: its real CPU demand is higher" in s.risks
    assert "CPU kept: throttling hides how much it needs" in s.risks


def test_a_throttled_container_may_still_be_raised() -> None:
    s = sizing.size(
        usage(cpu=[0.18] * 50, requests={"cpu": 0.1}, limits={"cpu": 0.2}, throttled=0.5), NOW
    )
    assert s.cpu and s.cpu.action == "raise" and s.cpu.target == 0.2


@pytest.mark.parametrize(("throttled", "held"), [(0.10, False), (0.11, True), (None, False)])
def test_the_throttling_threshold(throttled: float | None, held: bool) -> None:
    s = sizing.size(usage(cpu=[0.1] * 50, requests={"cpu": 1.0}, throttled=throttled), NOW)
    assert s.cpu and (s.cpu.action == "keep") is held


def test_after_an_oom_kill_memory_is_never_lowered() -> None:
    u = usage(memory=[100 * MI] * 50, requests={"memory": 512 * MI}, oom_killed_pods=2)
    s = sizing.size(u, NOW)
    assert s.memory and s.memory.action == "keep" and s.memory.target == 512 * MI
    assert "OOM-killed in 2 pods: its peak is its limit, not its demand" in s.risks
    assert "memory kept: OOM kills hide how much it needs" in s.risks


def test_an_oom_killed_leak_at_its_limit_asks_for_more_than_the_limit() -> None:
    """The lab's leaky: 256 MiB limit, killed there. It needs more than the limit allows."""
    u = usage(
        memory=[200 * MI, 256 * MI] * 25,
        requests={"memory": 128 * MI},
        limits={"memory": 256 * MI},
        oom_killed_pods=1,
    )
    s = sizing.size(u, NOW)
    assert s.memory and s.memory.action == "raise" and s.memory.target == 256 * MI
    assert "memory limit 256Mi is below the 308Mi it needs" in s.risks


def test_the_limit_wins_over_the_floor() -> None:
    """Order: headroom, floor, then the limit. A 5m limit keeps the request at 5m."""
    s = sizing.size(usage(cpu=[0.001] * 50, requests={}, limits={"cpu": 0.005}), NOW)
    assert s.cpu and s.cpu.target == 0.005


def test_cpu_follows_the_p95_not_a_rare_spike() -> None:
    s = sizing.size(usage(cpu=[0.1] * 99 + [2.0], requests={}), NOW)
    assert s.cpu and s.cpu.basis == 0.1 and s.cpu.target == 0.115
