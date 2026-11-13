"""Needs (slice 14.1a): what each autoscaled Workload needed, read from kube-state-metrics'
HPA series as every UTC hour's peak, stored per Contract for 8 weeks; nothing shown yet."""

import asyncio
import calendar
import importlib.util
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from squero import sizing, usage
from squero.contracts import Contract
from squero.store import Store, connect
from squero.usage import HPA, NEEDS_FOR, Target, UsageError, Workload
from tests.fake_prometheus import FakePrometheus
from tests.test_sizing_store import PROM, prometheus_contract, store  # noqa: F401
from tests.test_usage import _prom, cpu, deployment, mem

DAY = 86_400.0
H = 3600.0
NOW = 1000 * DAY  # midnight UTC
SHOP = Target("test", "http://prometheus", None, {}, ["shop"])
API = Workload("shop", "Deployment", "api")
N = 121  # two hours a minute apart, both ends sampled


def hpa(
    fake: FakePrometheus,
    replicas: Sequence[float | None] | None = None,
    name: str = "api",
    of: str = "api",
    kind: str = "Deployment",
    ns: str = "shop",
    there: Sequence[float | None] | None = None,
    **extra: str,
) -> None:
    """An HPA `name` of the Workload `of`, with `replicas` at each step, `there` the
    steps it exists at."""
    who = {"namespace": ns, "horizontalpodautoscaler": name, **extra}
    ref = {"scaletargetref_kind": kind, "scaletargetref_name": of}
    fake.add(f"{HPA}_info", [1.0] * N if there is None else there, **who, **ref)
    if replicas is not None:
        fake.add(f"{HPA}_status_current_replicas", replicas, **who)


def metric(
    fake: FakePrometheus,
    target: Sequence[float | None] | None,
    now: Sequence[float | None] | None,
    name: str = "cpu",
    kind: str = "utilization",
    hpa: str = "api",
    ns: str = "shop",
    **extra: str,
) -> None:
    """One metric the HPA scales on: its target and its current value at each step."""
    labels = {"namespace": ns, "horizontalpodautoscaler": hpa, **extra}
    labels |= {"metric_name": name, "metric_target_type": kind}
    if target is not None:
        fake.add(f"{HPA}_spec_target_metric", target, **labels)
    if now is not None:
        fake.add(f"{HPA}_status_target_metric", now, **labels)


def read(
    fake: FakePrometheus, t: Target = SHOP, start: float = NOW - 2 * H
) -> dict[Workload, dict[float, float]]:
    return usage.needs(_prom(fake, t), t, start, NOW)


# --- the read ----------------------------------------------------------------------


def test_a_need_is_the_replicas_times_the_current_value_over_the_target() -> None:
    """Four replicas at 75% of their requests against a target of 50%: six were needed,
    in each hour by its start; the HPA's Workload is its scale target, of any kind."""
    fake = FakePrometheus()
    hpa(fake, [4.0] * N)
    metric(fake, [50.0] * N, [75.0] * N)
    hpa(fake, [1.0] * N, name="db-scaler", of="db", kind="StatefulSet")
    metric(fake, [80.0] * N, [20.0] * N, hpa="db-scaler")
    assert read(fake) == {
        API: {NOW - 2 * H: 6.0, NOW - H: 6.0, NOW: 6.0},
        Workload("shop", "StatefulSet", "db"): {NOW - 2 * H: 0.25, NOW - H: 0.25, NOW: 0.25},
    }


def test_an_hour_keeps_its_peak_and_starts_on_the_hour() -> None:
    """A spike at the first hour's last step and one on the stroke of the next: each
    counts in its own hour."""
    fake = FakePrometheus()
    hpa(fake, [2.0] * N)
    now = [50.0] * N
    now[59], now[60], now[90] = 100.0, 150.0, 25.0
    metric(fake, [50.0] * N, now)
    assert read(fake)[API] == {NOW - 2 * H: 4.0, NOW - H: 6.0, NOW: 2.0}


def test_the_largest_metric_counts_each_against_its_own_target() -> None:
    """CPU at 60 of 50 percent, a queue at 30 of 10 per pod: the queue's three times.
    A current value is paired by its metric, its target's type (a resource metric's
    current value comes as a utilization and as an average) and its container."""
    fake = FakePrometheus()
    hpa(fake, [2.0] * N)
    metric(fake, [50.0] * N, [60.0] * N)
    metric(fake, None, [0.9] * N, kind="average")  # cores: never over a percentage
    metric(fake, [10.0] * N, [30.0] * N, name="queue_depth", kind="average")
    metric(fake, [100.0] * N, [50.0] * N, name="lag", kind="average")
    assert read(fake)[API][NOW] == 6.0
    fake = FakePrometheus()
    hpa(fake, [2.0] * N)
    metric(fake, [50.0] * N, [100.0] * N, container="app")
    metric(fake, [80.0] * N, [40.0] * N, container="sidecar")
    assert read(fake)[API][NOW] == 4.0
    fake = FakePrometheus()
    hpa(fake, [2.0] * N)
    metric(fake, [100.0] * N, [300.0] * N, name="requests", kind="value")
    metric(fake, [100.0] * N, [50.0] * N, name="requests", kind="average")
    assert read(fake)[API][NOW] == 6.0


def test_a_step_without_a_current_value_or_a_target_gives_no_need() -> None:
    """The first hour has no current value for one of two targets, the second no target
    at all, the third a target of zero: unknown, never a guess from the rest."""
    fake = FakePrometheus()
    hpa(fake, [2.0] * N)
    hour = 60
    metric(fake, [50.0] * hour + [None] * hour + [0.0], [75.0] * N)
    metric(fake, [10.0] * hour, [None] * hour + [30.0] * hour, name="queue", kind="average")
    assert read(fake) == {}
    metric(fake, [None] * hour + [10.0] * hour, [30.0] * N, name="lag", kind="value")
    assert read(fake) == {API: {NOW - H: 6.0}}


def test_no_replicas_is_a_need_of_none_at_all() -> None:
    """Scaled to zero (KEDA's, or by hand): nothing ran, nothing was needed, whatever
    the metric series say. An HPA whose replicas are not known gives nothing."""
    fake = FakePrometheus()
    hpa(fake, [0.0] * 60 + [3.0] * 61)
    metric(fake, [None] * 60 + [50.0] * 61, [None] * 60 + [100.0] * 61)
    hpa(fake, None, name="lost", of="lost")
    metric(fake, [50.0] * N, [100.0] * N, hpa="lost")
    assert read(fake) == {API: {NOW - 2 * H: 0.0, NOW - H: 6.0, NOW: 6.0}}


def test_a_scale_up_counts_the_replicas_that_were_there_a_step_before() -> None:
    """Three replicas at 83% go to five: the HPA reports five at once, with the
    utilization of the three that have metrics. Five were needed, not eight; a scale-down
    counts what is left. A count from before a gap in the series says nothing."""
    fake = FakePrometheus()
    hpa(fake, [3.0] * 30 + [5.0] * 60 + [3.0] * 31)
    metric(fake, [50.0] * N, [250 / 3] * 31 + [50.0] * 59 + [250 / 3] * 31)
    assert read(fake)[API] == pytest.approx({NOW - 2 * H: 5.0, NOW - H: 5.0, NOW: 5.0})
    fake = FakePrometheus()
    hpa(fake, [2.0] * 10 + [None] * 110 + [6.0])  # the hour's one step, after the gap
    metric(fake, [50.0] * N, [100.0] * N)
    assert read(fake)[API] == {NOW - 2 * H: 4.0, NOW: 12.0}


def test_a_workload_with_two_hpas_has_no_need_while_both_are_there() -> None:
    """A second HPA of the same Workload in the first hour only (one without replicas
    counts): unknown then, the one HPA's after."""
    for second in ([3.0] * N, None):
        fake = FakePrometheus()
        hpa(fake, [2.0] * N)
        metric(fake, [50.0] * N, [100.0] * N)
        hpa(fake, second, name="api-2", there=[1.0] * 60 + [None] * 61)
        metric(fake, [50.0] * N, [150.0] * N, hpa="api-2")
        assert read(fake) == {API: {NOW - H: 4.0, NOW: 4.0}}


def test_an_hpa_moved_to_another_workload_counts_for_each_in_its_time() -> None:
    fake = FakePrometheus()
    hpa(fake, [2.0] * N, there=[1.0] * 60 + [None] * 61)
    hpa(fake, None, of="web", there=[None] * 60 + [1.0] * 61)
    metric(fake, [50.0] * N, [100.0] * N)
    assert read(fake) == {
        API: {NOW - 2 * H: 4.0},
        Workload("shop", "Deployment", "web"): {NOW - H: 4.0, NOW: 4.0},
    }


def test_only_the_targets_namespaces_and_labels_are_read() -> None:
    """Another Contract's namespace and another cluster's series on a shared store,
    with the same HPA name: never read, never mixed in."""
    fake = FakePrometheus()
    eu = Target("eu", "http://thanos", None, {"cluster": "prod-eu"}, ["shop"])
    hpa(fake, [2.0] * N, cluster="prod-eu")
    metric(fake, [50.0] * N, [100.0] * N, cluster="prod-eu")
    hpa(fake, [9.0] * N, ns="bank", cluster="prod-eu")
    metric(fake, [50.0] * N, [100.0] * N, ns="bank", cluster="prod-eu")
    hpa(fake, [7.0] * N, name="us", of="us", cluster="prod-us")
    metric(fake, [50.0] * N, [100.0] * N, cluster="prod-us")  # the same HPA name, there
    metric(fake, [50.0] * N, [100.0] * N, hpa="us", cluster="prod-us")
    assert read(fake, eu) == {API: {NOW - 2 * H: 4.0, NOW - H: 4.0, NOW: 4.0}}
    assert all('namespace=~"shop"' in q and 'cluster="prod-eu"' in q for q in fake.queries)


def test_kube_state_metrics_scraped_without_honor_labels_is_read_the_same() -> None:
    """The HPA's namespace and a metric's container arrive as exported_*; `namespace`
    and `container` are kube-state-metrics' own."""
    t = Target("test", "http://prometheus", None, {}, ["shop"], ksm_namespace="exported_namespace")
    fake = FakePrometheus()
    own = {"ns": "monitoring", "exported_namespace": "shop", "container": "kube-state-metrics"}
    hpa(fake, [2.0] * N, **own)
    metric(fake, [50.0] * N, [100.0] * N, **own, exported_container="app")
    metric(fake, [80.0] * N, [40.0] * N, **own, exported_container="sidecar")
    hpa(fake, [9.0] * N, ns="shop", exported_namespace="bank")  # bank's, scraped from shop
    assert read(fake, t) == {API: {NOW - 2 * H: 4.0, NOW - H: 4.0, NOW: 4.0}}


class Seen(usage.Prom):
    """A Prom that keeps each range query's start, end and step."""

    def __init__(self, fake: FakePrometheus) -> None:
        super().__init__(SHOP, fake.client())
        self.ranges: list[tuple[float, float, int]] = []

    def range(self, promql: str, start: float, end: float, step: int) -> list[dict[str, Any]]:
        self.ranges.append((start, end, step))
        return super().range(promql, start, end, step)


def test_without_an_hpa_one_query_is_made_and_a_long_read_is_coarser() -> None:
    fake = FakePrometheus()
    prom = Seen(fake)
    assert usage.needs(prom, SHOP, NOW - 2 * H, NOW) == {}
    assert prom.ranges == [(NOW - 2 * H, NOW, 60)] and f"{HPA}_info" in fake.queries[0]
    hpa(fake, [2.0] * 3)
    metric(fake, [50.0] * 3, [100.0] * 3)
    prom = Seen(fake)
    found = usage.needs(prom, SHOP, NOW - NEEDS_FOR, NOW)
    assert prom.ranges == [(NOW - NEEDS_FOR, NOW, 540)] * 4  # under 10,000 points
    assert found == {API: {NOW - NEEDS_FOR: 4.0}}  # 0, 9 and 18 minutes in


# --- with the hourly read ------------------------------------------------------------


def shop_fake() -> FakePrometheus:
    """A Deployment with usage, and its HPA."""
    fake = FakePrometheus()
    (p,) = deployment(fake, "api", pods=1)
    cpu(fake, p, [0.1] * 100)
    mem(fake, p, [80.0 * 2**20] * 100)
    hpa(fake, [2.0] * 3)
    metric(fake, [50.0] * 3, [100.0] * 3)
    return fake


def test_needs_are_read_only_when_asked_from_each_clusters_hour_at_most_8_weeks_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = shop_fake()
    monkeypatch.setattr(usage, "Prom", lambda t: _prom(fake, t))
    c = prometheus_contract()
    found = usage.collect(c, [86400], NOW)
    assert found.needs == {} and not [q for q in fake.queries if "current_replicas" in q]
    starts: list[float] = []
    real = usage.needs

    def needs(prom: usage.Prom, t: Target, start: float, end: float) -> Any:
        starts.append(start)
        return real(prom, t, start, end)

    monkeypatch.setattr(usage, "needs", needs)
    found = usage.collect(c, [86400], NOW, {})
    assert found.needs == {"test": {API: {NOW - NEEDS_FOR: 4.0}}}
    usage.collect(c, [86400], NOW, {"test": NOW - 3 * H, "gone": NOW})
    usage.collect(c, [86400], NOW, {"test": NOW - NEEDS_FOR - H})
    assert starts == [NOW - NEEDS_FOR, NOW - 3 * H, NOW - NEEDS_FOR]


def test_a_failed_read_of_needs_stops_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake = shop_fake()
    monkeypatch.setattr(usage, "Prom", lambda t: _prom(fake, t))

    def needs(*args: Any) -> Any:
        raise UsageError("Prometheus error 422: too many samples")

    monkeypatch.setattr(usage, "needs", needs)
    with caplog.at_level(logging.WARNING):
        found = usage.collect(prometheus_contract(), [86400], NOW, {})
    assert found.clusters == {"test": None} and found.needs == {}
    assert [u.workload for _, u in found.by_window[86400]] == [API]
    assert "acme/test: its Needs not read: Prometheus error 422" in caplog.text


def test_the_labs_weekly_load_follows_the_wall_clock_for_every_pod() -> None:
    """demo/lab/load.py's `weekly`: by UTC time, never by a pod's age, so the pods an
    HPA starts agree; one share on nights and weekends, 3 on weekdays from 08:00 to
    18:00, 7 on Mondays from 09:00 to 12:00."""
    path = Path(__file__).parent.parent / "demo" / "lab" / "load.py"
    spec = importlib.util.spec_from_file_location("lab_load", path)
    assert spec and spec.loader
    load = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(load)

    def at(day: int, hour: int, minute: int = 0) -> float:
        return calendar.timegm((2026, 11, day, hour, minute, 0))  # the 16th is a Monday

    times = {
        7: [at(16, 9), at(16, 11, 59)],
        3: [at(16, 8), at(16, 12), at(17, 9), at(20, 17, 59)],
        1: [at(16, 7, 59), at(20, 18), at(21, 10), at(22, 10)],
    }
    for share, whens in times.items():
        assert [load.weekly(t) for t in whens] == [load.CPU * share] * len(whens)
    load.SHARE_WITH = "no-such-host.invalid"
    assert load.pods() == 1  # a failed lookup: the last count, at least this pod


# --- stored --------------------------------------------------------------------------

KEY = ("shop", "Deployment", "api")


def stored_row(
    hour: float, need: float, cluster: str = "test", name: str = "api"
) -> dict[str, Any]:
    where = {"cluster": cluster, "namespace": "shop", "kind": "Deployment", "name": name}
    return {**where, "hour": hour, "need": need}


@pytest.mark.anyio
async def test_an_hour_read_again_keeps_the_larger_need(store: Store) -> None:  # noqa: F811
    await store.save_needs("acme", "test", {KEY: {NOW: 2.0, NOW + H: 3.0}})
    await store.save_needs("acme", "test", {KEY: {NOW: 1.5, NOW + H: 4.5, NOW + 2 * H: 1.0}})
    await store.save_needs("acme", "edge", {("shop", "Deployment", "web"): {NOW - H: 7.0}})
    assert await store.needs("acme", {"test", "edge"}) == [
        stored_row(NOW - H, 7.0, "edge", "web"),
        stored_row(NOW, 2.0),
        stored_row(NOW + H, 4.5),
        stored_row(NOW + 2 * H, 1.0),
    ]
    assert await store.needs_since("acme") == {"test": NOW + 2 * H, "edge": NOW - H}
    # a cluster no longer in the Contract is not shown; nor an hour before `since`
    assert [r["cluster"] for r in await store.needs("acme", {"test"})] == ["test"] * 3
    assert await store.needs("acme", {"test", "edge"}, NOW + H) == [
        stored_row(NOW + H, 4.5),
        stored_row(NOW + 2 * H, 1.0),
    ]


@pytest.mark.anyio
async def test_needs_are_kept_8_weeks(store: Store) -> None:  # noqa: F811
    old, kept = NOW - NEEDS_FOR - H, NOW - NEEDS_FOR
    await store.save_needs("acme", "test", {KEY: {old: 1.0, kept: 2.0, NOW: 3.0}})
    await store.save_needs("bank", "test", {KEY: {old: 9.0}})
    await store.prune_sizings("acme", NOW)
    assert [r["hour"] for r in await store.needs("acme", {"test"})] == [kept, NOW]
    assert [r["hour"] for r in await store.needs("bank", {"test"})] == [old]  # bank's own prune


@pytest.mark.anyio
async def test_a_contracts_needs_never_reach_another(store: Store) -> None:  # noqa: F811
    await store.save_needs("acme", "test", {KEY: {NOW: 2.0}})
    await store.save_needs("bank", "test", {KEY: {NOW: 9.0, NOW + H: 8.0}})
    assert await store.needs("acme", {"test"}) == [stored_row(NOW, 2.0)]
    assert await store.needs("bank", {"test"}) == [stored_row(NOW, 9.0), stored_row(NOW + H, 8.0)]
    assert await store.needs_since("acme") == {"test": NOW}
    assert await store.needs_since("nobody") == {}


@pytest.mark.anyio
async def test_each_run_stores_its_needs_and_the_next_reads_on_from_them(
    store: Store,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first run reads 8 weeks back; the next starts at the newest hour stored (never
    further back than 8 weeks), and an hour read twice keeps its larger need."""
    fake = shop_fake()
    monkeypatch.setattr(usage, "Prom", lambda t: _prom(fake, t))
    c = prometheus_contract()
    assert await sizing.store_run(store, c, NOW) is not None
    first = NOW - NEEDS_FOR
    assert await store.needs(c.id, {"test"}) == [stored_row(first, 4.0)]
    starts: list[float] = []
    reads = iter([{NOW: 2.0, NOW + H: 1.0}, {NOW + H: 3.0, NOW + 2 * H: 1.5}])

    def needs(prom: usage.Prom, t: Target, start: float, end: float) -> Any:
        starts.append(start)
        return {API: next(reads)}

    monkeypatch.setattr(usage, "needs", needs)
    assert await sizing.store_run(store, c, NOW + H) is not None
    assert await sizing.store_run(store, c, NOW + 2 * H) is not None
    assert starts == [first + H, NOW + H]  # 8 weeks before the run; then the newest hour
    assert [(r["hour"], r["need"]) for r in await store.needs(c.id, {"test"})] == [
        (NOW, 2.0),  # the first read's hour is past its 8 weeks
        (NOW + H, 3.0),
        (NOW + 2 * H, 1.5),
    ]


def test_each_demo_contract_stores_only_its_own_needs(
    two_contracts: dict[str, Contract], database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both demo Contracts end to end on one fake Prometheus, an HPA in every namespace
    of each: a run stores the Needs of its own Contract's namespaces only."""
    fake = FakePrometheus()
    for i, c in enumerate(two_contracts.values()):
        for cl in c.clusters:
            for ns in cl.namespaces:
                (p,) = deployment(fake, f"{c.id}-api", pods=1, ns=ns)
                cpu(fake, p, [0.1] * 100, ns=ns)
                mem(fake, p, [80.0 * 2**20] * 100, ns=ns)
                hpa(fake, [2.0 + i] * 3, name=f"{c.id}-api", of=f"{c.id}-api", ns=ns)
                metric(fake, [50.0] * 3, [100.0] * 3, hpa=f"{c.id}-api", ns=ns)
    monkeypatch.setattr(usage, "Prom", lambda t: _prom(fake, t))

    async def go() -> dict[str, set[tuple[str, str, float]]]:
        async with connect(database_url) as pool:
            s = Store(pool)
            await s.migrate()
            out = {}
            for c in two_contracts.values():
                c = c.model_copy(update={"integrations": [*c.integrations, PROM]})
                assert await sizing.store_run(s, c, NOW) is not None
                rows = await s.needs(c.id, {cl.name for cl in c.clusters})
                out[c.id] = {(r["namespace"], r["name"], r["need"]) for r in rows}
            return out

    found = asyncio.run(go())
    for i, (cid, c) in enumerate(two_contracts.items()):
        spaces = {ns for cl in c.clusters for ns in cl.namespaces}
        assert found[cid] == {(ns, f"{cid}-api", 4.0 + 2 * i) for ns in spaces}
