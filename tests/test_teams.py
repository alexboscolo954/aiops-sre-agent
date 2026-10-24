"""Cost by label and team (slice 10.2b): the allocation's pod labels come from
kube-state-metrics' kube_pod_labels, a Workload's newest pod's, and are stored on each
row; teams are matched when shown, the first rule winning, else "(no team)"."""

import asyncio
from typing import Any

import pytest

from aiops_agent import contracts, sizing, usage
from aiops_agent.contracts import Contract
from aiops_agent.store import Store, connect
from aiops_agent.usage import Target
from tests.conftest import make_contract
from tests.fake_prometheus import FakePrometheus
from tests.test_sizing_store import MI, NOW, PROM, container, row, rows_of
from tests.test_usage import FLAT, SHOP, _prom, cpu, deployment, mem, prom

DAY = 86_400
RULES = [
    {"team": "payments", "namespace": "pay*"},
    {"team": "storefront", "labels": {"team": "storefront"}},
    {"team": "eu-shop", "cluster": "eu"},
]


def allocated(allocation: dict[str, Any] | None = None, priced: bool = True) -> Contract:
    data = make_contract(clusters={"test": ["shop", "pay"], "eu": ["shop"]}).model_dump()
    data["integrations"].append({"name": "prometheus", "url": "http://prometheus"})
    data["allocation"] = (
        allocation if allocation is not None else {"labels": ["team"], "teams": RULES}
    )
    if priced:
        data["prices"] = {"cpu": 0.05, "memory": 0.01}
    return contracts.build(data)


def r(cluster: str, ns: str, name: str, cores: float, **labels: str) -> dict[str, Any]:
    """A stored row asking `cores` on 1 pod and wasting 1 core; no `labels` when none
    are given, as a row stored before 10.2b."""
    extra = {"labels": labels} if labels else {}
    workload = f"{cluster}/{ns}/Deployment/{name}/app"
    asked = {"cpu": cores, "memory": 0.0}
    return row(name, cluster, namespace=ns, workload=workload, requests=asked, **extra)


ROWS = [
    r("test", "shop", "api", 2.0, team="storefront"),
    r("test", "pay", "billing", 4.0, team="storefront"),  # the namespace rule comes first
    r("eu", "shop", "web", 1.0, team="storefront"),  # the label rule before the cluster's
    r("eu", "shop", "db", 3.0),  # stored before 10.2b: the cluster rule still matches
    r("test", "shop", "idle", 0.5),  # no rule matches
]
CORE = 0.05 * 730  # a core's month


# --- the Contract ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("allocation", "error"),
    [
        ({"labels": ["app.team", "app_team"]}, "one label in kube-state-metrics"),
        ({"labels": ["team"], "teams": [{"team": "x", "labels": {"owner": "y"}}]}, "not in labels"),
        ({"teams": [{"team": "x"}]}, "needs cluster, namespace or labels"),
        ({"teams": [{"team": "(no team)", "namespace": "shop"}]}, "team"),
        ({"teams": [{"team": "x", "cluster": "nope"}]}, "no cluster 'nope'"),
        ({"labels": ["a/b/c"]}, "labels"),
        ({"label": ["team"]}, "label"),
    ],
)
def test_the_allocation_validates(allocation: dict[str, Any], error: str) -> None:
    with pytest.raises(ValueError, match=error):
        allocated(allocation)


def test_label_keys_become_kube_state_metrics_names() -> None:
    assert contracts.ksm_label("team") == "label_team"
    assert contracts.ksm_label("app.kubernetes.io/team") == "label_app_kubernetes_io_team"


def test_groupings_are_the_ones_the_contract_has() -> None:
    assert sizing.groupings(allocated()) == ["namespace", "team", "label:team"]
    assert sizing.groupings(allocated({"labels": ["team"]})) == ["namespace", "label:team"]
    for by in ("team", "label:owner", "pods"):
        with pytest.raises(ValueError, match="groups by namespace"):
            sizing.allocate(ROWS, allocated({"labels": ["team"]}), by)


# --- reading the labels ------------------------------------------------------------


def labelled(
    fake: FakePrometheus, pod: str, created: float, ns: str = "shop", **found: str
) -> None:
    fake.add("kube_pod_created", created, namespace=ns, pod=pod)
    fake.add(
        "kube_pod_labels",
        1,
        namespace=ns,
        pod=pod,
        **{contracts.ksm_label(k): v for k, v in found.items()},
    )


def test_a_workload_gets_its_newest_pods_labels_and_only_the_listed_ones() -> None:
    fake = FakePrometheus()
    new, old = deployment(fake, pods=2)  # the newest sorts first by name
    for p in (old, new):
        cpu(fake, p, FLAT)
    labelled(fake, old, 100, team="old")
    labelled(fake, new, 200, team="new", owner="not-listed")
    labelled(fake, new, 999, ns="bank", team="theirs")  # another namespace's pod of that name
    (found,) = usage.usage(prom(fake), SHOP, DAY, end=DAY, labels=["team"]).rows
    assert found.labels == {"team": "new"}


def test_a_newest_pod_without_the_label_has_none() -> None:
    fake = FakePrometheus()
    new, old = deployment(fake, pods=2)  # the newest sorts first by name
    for p in (old, new):
        cpu(fake, p, FLAT)
    labelled(fake, old, 100, team="old")
    labelled(fake, new, 200)
    (found,) = usage.usage(prom(fake), SHOP, DAY, end=DAY, labels=["team"]).rows
    assert found.labels == {}


@pytest.mark.parametrize("labelled_first", [True, False])
def test_of_one_pods_series_the_labelled_one_wins(labelled_first: bool) -> None:
    """kube-state-metrics restarted with the allowlist: the pod has a series from
    before (no label) and one from after, whichever Prometheus returns first."""
    fake = FakePrometheus()
    (p,) = deployment(fake, pods=1)
    cpu(fake, p, FLAT)
    fake.add("kube_pod_created", 100, namespace="shop", pod=p, uid="u1")
    series = [{"instance": "new", "label_team": "pay"}, {"instance": "old"}]
    for extra in series if labelled_first else series[::-1]:
        fake.add("kube_pod_labels", 1, namespace="shop", pod=p, uid="u1", **extra)
    (found,) = usage.usage(prom(fake), SHOP, DAY, end=DAY, labels=["team"]).rows
    assert found.labels == {"team": "pay"}


def test_a_statefulset_pods_newest_incarnation_wins() -> None:
    """db-0 recreated under the same name: its uid tells the two apart."""
    fake = FakePrometheus()
    fake.add(
        "kube_pod_owner", 1, namespace="shop", pod="db-0", owner_kind="StatefulSet", owner_name="db"
    )
    cpu(fake, "db-0", FLAT)
    for uid, created, team in (("new", 200, "a"), ("old", 100, "z")):
        fake.add("kube_pod_created", created, namespace="shop", pod="db-0", uid=uid)
        fake.add("kube_pod_labels", 1, namespace="shop", pod="db-0", uid=uid, label_team=team)
    (found,) = usage.usage(prom(fake), SHOP, DAY, end=DAY, labels=["team"]).rows
    assert found.labels == {"team": "a"}  # not z, which sorts last


def test_no_labels_listed_no_label_queries() -> None:
    fake = FakePrometheus()
    (p,) = deployment(fake, pods=1)
    cpu(fake, p, FLAT)
    labelled(fake, p, 100, team="x")
    (found,) = usage.usage(prom(fake), SHOP, DAY, end=DAY).rows
    assert found.labels == {}
    assert not [q for q in fake.queries if "kube_pod_labels" in q or "kube_pod_created" in q]


def test_labels_are_found_without_honor_labels() -> None:
    """kube-state-metrics scraped without honor_labels: the pod's namespace and name
    are exported_*, and the label queries must use them like the owner queries."""
    t = Target("kind", "http://prometheus", None, {}, ["shop"], ksm_namespace="exported_namespace")
    fake = FakePrometheus()
    ksm = {"exported_namespace": "shop", "namespace": "monitoring", "pod": "ksm-0"}
    fake.add(
        "kube_pod_owner", 1, exported_pod="solo", owner_kind="<none>", owner_name="<none>", **ksm
    )
    cpu(fake, "solo", FLAT)
    fake.add("kube_pod_created", 5, exported_pod="solo", **ksm)
    fake.add("kube_pod_labels", 1, exported_pod="solo", label_team="pay", **ksm)
    (found,) = usage.usage(usage.Prom(t, fake.client()), t, DAY, end=DAY, labels=["team"]).rows
    assert found.labels == {"team": "pay"}


def test_rows_store_the_labels_only_when_the_contract_lists_some() -> None:
    u = container()
    u.labels = {"team": "pay"}
    (listed,) = rows_of(u, c=allocated())
    assert listed["labels"] == {"team": "pay"}
    (plain,) = rows_of(u, c=allocated({}))
    assert "labels" not in plain


def test_each_demo_contract_reads_only_its_own_pods_labels(
    two_contracts: dict[str, Contract], database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both demo Contracts end to end on one fake Prometheus, every pod named alike:
    each run stores only its own namespaces' labels, though the other's pods are newer."""
    fake = FakePrometheus()
    for created, c in enumerate(two_contracts.values()):
        for cl in c.clusters:
            for ns in cl.namespaces:
                (p,) = deployment(fake, "api", pods=1, ns=ns)
                cpu(fake, p, [0.1] * 1441, ns=ns)
                mem(fake, p, [80 * MI] * 1441, ns=ns)
                labelled(fake, p, 1000 + created, ns=ns, team=c.id)
    monkeypatch.setattr(usage, "Prom", lambda t: _prom(fake, t))

    async def go() -> dict[str, list[dict[str, str]]]:
        async with connect(database_url) as pool:
            store = Store(pool)
            await store.migrate()
            out = {}
            for c in two_contracts.values():
                c = c.model_copy(
                    update={
                        "integrations": [*c.integrations, PROM],
                        "allocation": contracts.Allocation(labels=["team"]),
                    }
                )
                assert await sizing.store_run(store, c, NOW) is not None
                rows, _ = await store.latest_sizings(c.id, {cl.name for cl in c.clusters})
                out[c.id] = [r["labels"] for r in rows]
            return out

    found = asyncio.run(go())
    assert found["demo-shop"] and found["demo-bank"]
    for cid, labels in found.items():
        assert labels == [{"team": cid}] * len(labels)


# --- grouping ----------------------------------------------------------------------


def test_teams_by_first_matching_rule_cost_their_requests_by_hand() -> None:
    out = sizing.allocate(ROWS, allocated(), "team")
    groups = {g["group"]: g for g in out["groups"]}
    # storefront: test/shop/api and eu/shop/web, across clusters
    assert {k: g["workloads"] for k, g in groups.items()} == {
        "payments": 1,
        "storefront": 2,
        "eu-shop": 1,
        "(no team)": 1,
    }
    assert {k: g["cost"]["requests"] for k, g in groups.items()} == pytest.approx(
        {"payments": 4 * CORE, "storefront": 3 * CORE, "eu-shop": 3 * CORE, "(no team)": 0.5 * CORE}
    )
    assert [g["group"] for g in out["groups"]][:2] == [
        "payments",
        "eu-shop",
    ]  # by requests, then name
    assert out["by"] == "team" and out["warnings"] == []


def test_a_label_groups_its_values_and_the_rows_without_it() -> None:
    out = sizing.allocate(ROWS, allocated(), "label:team")
    got = {g["group"]: g["workloads"] for g in out["groups"]}
    assert got == {"storefront": 3, "(no team)": 2}
    owner = allocated({"labels": ["team", "owner"]})
    (none,) = sizing.allocate(ROWS, owner, "label:owner")["groups"]
    assert (none["group"], none["workloads"]) == ("(no owner)", 5)


@pytest.mark.parametrize("by", ["namespace", "team", "label:team"])
def test_every_grouping_adds_up_to_the_contracts_totals(by: str) -> None:
    c = allocated()
    total = sizing.report(ROWS, {}, c)["cost"]
    groups = sizing.allocate(ROWS, c, by)["groups"]
    assert sum(g["cost"]["requests"] for g in groups) == pytest.approx(total["requests"])
    assert sum(g["cost"]["waste"] for g in groups) == pytest.approx(total["waste"])
    assert sum(g["workloads"] for g in groups) == len(ROWS)


def test_a_cluster_where_no_pod_has_the_label_is_warned_about() -> None:
    c = allocated()
    rows = [r("test", "shop", "api", 1.0, team="x"), r("eu", "shop", "db", 1.0)]
    warning = (
        "eu: no pod has label team; kube-state-metrics needs --metric-labels-allowlist=pods=[team]"
    )
    assert sizing.allocate(rows, c, "label:team")["warnings"] == [warning]
    assert sizing.allocate(rows, c, "team")["warnings"] == [warning]  # a rule reads team
    assert sizing.allocate(rows, c, "namespace")["warnings"] == []
    no_label_rules = allocated({"labels": ["team"], "teams": [{"team": "a", "cluster": "eu"}]})
    assert sizing.allocate(rows, no_label_rules, "team")["warnings"] == []


def test_unpriced_teams_rank_a_core_like_4_gib() -> None:
    c = allocated(priced=False)
    out = sizing.allocate(ROWS, c, "team")
    assert out["currency"] is None and all(g["cost"] is None for g in out["groups"])
    assert out["groups"][0]["group"] == "payments"


def test_sizing_cost_refuses_a_grouping_the_contract_lacks(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from aiops_agent import cli

    monkeypatch.setattr(cli, "contract", lambda settings, cid: allocated())
    assert cli.main(["sizing", "cost", "--contract", "acme", "--by", "label:owner"]) == 2
    assert "acme groups by namespace, team, label:team" in capsys.readouterr().err
