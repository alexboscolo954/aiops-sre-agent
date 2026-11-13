"""Sizings held by an HPA (slice 14.3): a Sizing that would change a request an HPA divides
by (a Utilization target) is marked held, with the same threshold as an AverageValue and
the manifest change that frees it. Its Waste still counts; the Actuator is unchanged."""

import asyncio
import logging
from typing import Any

import pytest

from squero import contracts, hubmcp, sizing, usage, webapp
from squero.contracts import Contract
from squero.servers import sizing as tool
from squero.store import Store, connect
from squero.usage import HPA, ContainerUsage, Divides, Target, UsageError, Workload
from tests.fake_prometheus import FakePrometheus
from tests.test_sizing_policy import lab, run_show
from tests.test_sizing_store import PROM, WEEK, container, prometheus_contract
from tests.test_usage import _prom, cpu, deployment, mem

DAY = 86_400.0
MI = 2**20
GI = 2**30
NOW = 1000 * DAY
SHOP = Target("test", "http://prometheus", None, {}, ["shop"])
API = Workload("shop", "Deployment", "api")


def hpa(
    fake: FakePrometheus,
    name: str = "api",
    of: str = "api",
    kind: str = "Deployment",
    ns: str = "shop",
    **extra: str,
) -> None:
    ref = {"scaletargetref_kind": kind, "scaletargetref_name": of}
    fake.add(f"{HPA}_info", 1.0, namespace=ns, horizontalpodautoscaler=name, **ref, **extra)


def target(
    fake: FakePrometheus,
    percent: float,
    name: str = "cpu",
    kind: str = "utilization",
    hpa: str = "api",
    ns: str = "shop",
    **extra: str,
) -> None:
    labels = {"namespace": ns, "horizontalpodautoscaler": hpa, **extra}
    labels |= {"metric_name": name, "metric_target_type": kind}
    fake.add(f"{HPA}_spec_target_metric", percent, **labels)


# --- the read ----------------------------------------------------------------------


def test_the_utilization_targets_of_cpu_and_memory_are_read_per_workload() -> None:
    """Of the whole pod or of one container; an AverageValue or a Value target divides
    by no request, nor does a Utilization of anything else; an HPA's Workload is its
    scale target."""
    fake = FakePrometheus()
    hpa(fake)
    target(fake, 80.0, name="memory", container="app")
    target(fake, 50.0)  # listed in order, whatever order they come in
    target(fake, 0.2, kind="average")  # cores: already free
    target(fake, 100.0, name="requests", kind="value")
    target(fake, 70.0, name="queue")  # not a request
    hpa(fake, name="db-scaler", of="db", kind="StatefulSet")
    target(fake, 60.0, hpa="db-scaler")
    target(fake, 90.0, hpa="orphan")  # no info series: no Workload to give it to
    assert usage.scaled(_prom(fake, SHOP), SHOP, NOW) == {
        API: [Divides("api", "cpu", "", 50.0), Divides("api", "memory", "app", 80.0)],
        Workload("shop", "StatefulSet", "db"): [Divides("db-scaler", "cpu", "", 60.0)],
    }
    assert not [q for q in fake.queries if "last_over_time" in q]  # as it is now


def test_only_the_targets_namespaces_and_labels_are_read() -> None:
    fake = FakePrometheus()
    eu = Target("eu", "http://thanos", None, {"cluster": "prod-eu"}, ["shop"])
    hpa(fake, cluster="prod-eu")
    target(fake, 50.0, cluster="prod-eu")
    hpa(fake, ns="bank", cluster="prod-eu")
    target(fake, 10.0, ns="bank", cluster="prod-eu")
    target(fake, 20.0, cluster="prod-us")  # the same HPA name, another cluster
    assert usage.scaled(_prom(fake, eu), eu, NOW) == {API: [Divides("api", "cpu", "", 50.0)]}
    assert all('namespace=~"shop"' in q and 'cluster="prod-eu"' in q for q in fake.queries)


def test_without_honor_labels_the_hpas_own_labels_are_the_exported_ones() -> None:
    t = Target("test", "http://prometheus", None, {}, ["shop"], ksm_namespace="exported_namespace")
    fake = FakePrometheus()
    own = {"ns": "monitoring", "exported_namespace": "shop", "container": "kube-state-metrics"}
    hpa(fake, **own)
    target(fake, 50.0, **own)
    target(fake, 80.0, name="memory", **own, exported_container="app")
    hpa(fake, name="theirs", ns="shop", exported_namespace="bank")
    target(fake, 10.0, hpa="theirs", ns="shop", exported_namespace="bank")
    assert usage.scaled(_prom(fake, t), t, NOW) == {
        API: [
            Divides("api", "cpu", "kube-state-metrics", 50.0),  # the scrape target's: see held
            Divides("api", "memory", "app", 80.0),
        ]
    }


def test_without_an_hpa_one_query_is_made() -> None:
    fake = FakePrometheus()
    assert usage.scaled(_prom(fake, SHOP), SHOP, NOW) == {}
    assert len(fake.queries) == 1 and f"{HPA}_info" in fake.queries[0]


def shop_fake() -> FakePrometheus:
    fake = FakePrometheus()
    lab(fake)
    hpa(fake)
    target(fake, 50.0)
    return fake


def test_a_failed_read_of_the_targets_stops_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake = shop_fake()
    monkeypatch.setattr(usage, "Prom", lambda t: _prom(fake, t))
    c = prometheus_contract()
    assert usage.collect(c, [86400], NOW).scaled == {"test": {API: [Divides("api", "cpu", "", 50)]}}

    def scaled(*args: Any) -> Any:
        raise UsageError("Prometheus error 503: busy")

    monkeypatch.setattr(usage, "scaled", scaled)
    with caplog.at_level(logging.WARNING):
        found = usage.collect(c, [86400], NOW)
    assert found.clusters == {"test": None} and found.scaled == {}
    assert len(found.by_window[86400]) == 4
    assert "acme/test: its HPAs' targets not read: Prometheus error 503" in caplog.text


# --- the mark ------------------------------------------------------------------------


def sidecar(**kw: Any) -> ContainerUsage:
    u = container(**kw)
    u.container = "sidecar"
    return u


def rows(
    *us: ContainerUsage, divides: list[Divides], c: Contract | None = None, cluster: str = "test"
) -> dict[str, dict[str, Any]]:
    found = {WEEK: [("test", u) for u in us]}
    out = sizing.rows(c or prometheus_contract(), found, NOW, {cluster: {API: divides}})
    return {r["container"]: r for r in out}


POD = """# HorizontalPodAutoscaler shop/api, its cpu metric:
# 50% of the pod's cpu requests now (1200m), as a value.
# Apply it before any request changes: a request cut first scales it out.
target:
  type: AverageValue
  averageValue: 600m"""


def test_a_request_its_hpa_divides_by_is_held_with_the_same_threshold_as_a_value() -> None:
    """50% of the pod's requests, every container's summed (1 core and 200m): 600m.
    Every container whose Sizing would change that request is held; memory, which the
    HPA doesn't scale on, is free. The Waste is what it was."""
    app = container()
    side = sidecar(request={"cpu": 0.2, "memory": float(GI)})
    free = rows(app, side, divides=[])
    got = rows(app, side, divides=[Divides("api", "cpu", "", 50.0)])
    assert got["app"]["cpu"]["held"] == {
        "hpa": "api",
        "percent": 50.0,
        "average": pytest.approx(0.6),
        "change": POD,
    }
    assert got["sidecar"]["cpu"]["held"] == got["app"]["cpu"]["held"]
    assert got["sidecar"]["cpu"]["action"] == "lower"
    for name in ("app", "sidecar"):
        assert "held" not in got[name]["memory"] and "held" not in free[name]["cpu"]
        assert got[name]["waste"] == free[name]["waste"] and got[name]["waste"]["cpu"] > 0
        assert got[name]["risks"] == free[name]["risks"]


def test_a_learning_or_excluded_containers_request_counts_in_the_pods() -> None:
    """The HPA divides by every container's request, sized here or not."""
    app = container()
    by = [Divides("api", "cpu", "", 50.0)]
    young = rows(app, sidecar(hours=2, request={"cpu": 0.2}), divides=by)
    assert young["sidecar"]["state"] == "learning" and "cpu" not in young["sidecar"]
    assert young["app"]["cpu"]["held"]["average"] == pytest.approx(0.6)
    data = prometheus_contract().model_dump()
    data["sizing"] = {"rules": [{"container": "sidecar", "policy": "off"}]}
    off = rows(app, sidecar(request={"cpu": 0.2}), divides=by, c=contracts.build(data))
    assert off["sidecar"]["state"] == "excluded"
    assert off["app"]["cpu"]["held"]["average"] == pytest.approx(0.6)


def test_a_per_container_metric_holds_that_container_by_its_own_request() -> None:
    app, side = container(), sidecar(request={"cpu": 0.2, "memory": float(GI)})
    got = rows(app, side, divides=[Divides("api", "cpu", "sidecar", 50.0)])
    assert "held" not in got["app"]["cpu"]
    held = got["sidecar"]["cpu"]["held"]
    assert held["average"] == pytest.approx(0.1)
    assert held["change"].splitlines() == [
        "# HorizontalPodAutoscaler shop/api, its cpu metric of container sidecar:",
        "# 50% of container sidecar's cpu request now (200m), as a value.",
        "# Apply it before any request changes: a request cut first scales it out.",
        "target:",
        "  type: AverageValue",
        "  averageValue: 100m",
    ]


def test_a_container_label_that_names_no_container_is_the_whole_pods() -> None:
    """kube-state-metrics scraped without honor_labels: `container` is its own."""
    app, side = container(), sidecar(request={"cpu": 0.2, "memory": float(GI)})
    got = rows(app, side, divides=[Divides("api", "cpu", "kube-state-metrics", 50.0)])
    assert got["app"]["cpu"]["held"]["change"] == POD
    assert got["sidecar"]["cpu"]["held"]["average"] == pytest.approx(0.6)


def test_a_kept_request_is_not_held_a_raised_one_is() -> None:
    by = [Divides("api", "cpu", "", 50.0), Divides("api", "memory", "", 80.0)]
    kept = rows(container(request={"cpu": 0.115, "memory": float(GI)}), divides=by)["app"]
    assert kept["cpu"]["action"] == "keep" and "held" not in kept["cpu"]
    assert kept["memory"]["held"]["change"].splitlines()[1:] == [
        "# 80% of the pod's memory requests now (1024Mi), as a value.",
        "# Apply it before any request changes: a request cut first scales it out.",
        "target:",
        "  type: AverageValue",
        "  averageValue: 819Mi",
    ]
    low = rows(container(request={"cpu": 0.05, "memory": float(GI)}), divides=by)["app"]
    assert low["cpu"]["action"] == "raise" and low["cpu"]["held"]["average"] == pytest.approx(0.025)


def test_kedas_hpa_gets_the_change_for_its_scaled_objects_trigger() -> None:
    """KEDA names the HPA of ScaledObject `api` keda-hpa-api: the trigger's form, the
    value a quoted quantity, the container named for a per-container trigger."""
    app, side = container(), sidecar(request={"cpu": 0.2, "memory": float(GI)})
    got = rows(app, side, divides=[Divides("keda-hpa-api", "cpu", "", 50.0)])
    assert got["app"]["cpu"]["held"]["change"].splitlines() == [
        "# ScaledObject shop/api (KEDA), its cpu trigger:",
        "# 50% of the pod's cpu requests now (1200m), as a value.",
        "# Apply it before any request changes: a request cut first scales it out.",
        "- type: cpu",
        "  metricType: AverageValue",
        "  metadata:",
        '    value: "600m"',
    ]
    got = rows(app, side, divides=[Divides("keda-hpa-api", "memory", "app", 80.0)])
    assert got["app"]["memory"]["held"]["change"].splitlines()[3:] == [
        "- type: memory",
        "  metricType: AverageValue",
        "  metadata:",
        '    value: "819Mi"',
        '    containerName: "app"',
    ]
    plain = rows(app, side, divides=[Divides("my-keda-hpa-api", "cpu", "", 50.0)])
    assert plain["app"]["cpu"]["held"]["change"].startswith("# HorizontalPodAutoscaler shop/my-")


def test_without_a_request_to_go_by_it_is_held_with_no_value() -> None:
    got = rows(container(request={}), divides=[Divides("api", "cpu", "", 50.0)])["app"]
    assert got["cpu"]["action"] == "set"
    assert got["cpu"]["held"] == {"hpa": "api", "percent": 50.0, "average": None, "change": None}


def test_another_workloads_or_clusters_hpa_holds_nothing() -> None:
    by = [Divides("api", "cpu", "", 50.0)]
    assert "held" not in rows(container(), divides=by, cluster="other")["app"]["cpu"]
    web = container()
    web.workload = Workload("shop", "Deployment", "web")
    assert "held" not in rows(web, divides=by)["app"]["cpu"]
    first = [Divides("a", "cpu", "", 40.0), Divides("b", "cpu", "", 60.0)]  # two HPAs: the first
    assert rows(container(), divides=first)["app"]["cpu"]["held"]["hpa"] == "a"


# --- shown ---------------------------------------------------------------------------


def test_the_triage_agents_tool_reads_a_held_row_as_any_other() -> None:
    """Its output is the model's: unchanged by this slice, so no eval reruns."""
    c = prometheus_contract()
    free = rows(container(), divides=[])["app"]
    by = rows(container(), divides=[Divides("api", "cpu", "", 50.0)])["app"]
    assert "held" in by["cpu"] and tool.container(by, c) == tool.container(free, c)


def test_the_api_and_the_hub_mcp_show_a_held_request_with_its_change() -> None:
    by = rows(container(), divides=[Divides("api", "cpu", "", 50.0)])["app"]
    c = webapp.Container.model_validate(by)
    assert c.cpu and c.cpu.held and c.cpu.held.hpa == "api" and c.cpu.held.percent == 50
    assert c.memory and c.memory.held is None
    assert hubmcp._resource("cpu", c.cpu) == {
        "request": "1000m",
        "sizing": "115m",
        "action": "lower",
        "held": c.cpu.held.change,
    }
    assert "held" not in (hubmcp._resource("memory", c.memory) or {})
    bare = rows(container(request={}), divides=[Divides("api", "cpu", "", 50.0)])["app"]
    none = webapp.Container.model_validate(bare).cpu
    assert (hubmcp._resource("cpu", none) or {})["held"] == "by its HPA api"


def test_show_says_which_requests_are_held(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = run_show(monkeypatch, capsys, shop_fake())
    assert (
        "test/shop/Deployment/api/app (production): cpu lower 1000m -> 115m (held by its "
        "HPA api: free as AverageValue 500m), memory lower 1024Mi -> 96Mi" in out
    )
    assert "test/shop/Deployment/db/app (production): cpu lower 1000m -> 115m, memory" in out


def test_each_demo_contract_is_held_only_by_its_own_hpas(
    two_contracts: dict[str, Contract], database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both demo Contracts on one fake Prometheus, the same Workload name in each, an
    HPA only in demo-bank's namespaces: stored, bank's requests are held and shop's
    are not."""
    fake = FakePrometheus()
    for c in two_contracts.values():
        for cl in c.clusters:
            for ns in cl.namespaces:
                (p,) = deployment(fake, "api", pods=1, ns=ns)
                cpu(fake, p, [0.1] * 1441, ns=ns)
                mem(fake, p, [80.0 * MI] * 1441, ns=ns)
                for res, value in (("cpu", 1.0), ("memory", float(GI))):
                    labels = {"namespace": ns, "pod": p, "container": "app", "resource": res}
                    fake.add("kube_pod_container_resource_requests", value, **labels)
                if c.id == "demo-bank":
                    hpa(fake, ns=ns)
                    target(fake, 50.0, ns=ns)
    monkeypatch.setattr(usage, "Prom", lambda t: _prom(fake, t))

    async def go() -> dict[str, list[Any]]:
        async with connect(database_url) as pool:
            s = Store(pool)
            await s.migrate()
            out = {}
            for c in two_contracts.values():
                c = c.model_copy(update={"integrations": [*c.integrations, PROM]})
                assert await sizing.store_run(s, c, NOW) is not None
                stored, _ = await s.latest_sizings(c.id, {cl.name for cl in c.clusters})
                assert stored and all(r["cpu"]["action"] == "lower" for r in stored)
                out[c.id] = [r["cpu"].get("held", {}).get("average") for r in stored]
            return out

    found = asyncio.run(go())
    assert set(found["demo-bank"]) == {0.5} and set(found["demo-shop"]) == {None}
