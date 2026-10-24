"""Allocation by namespace (slice 10.2a): stored Sizings grouped by each cluster's
namespace, what their requests and waste cost, ranked by the requests."""

import json
from typing import Any

import pytest

from aiops_agent import sizing
from aiops_agent.usage import Workload
from tests.test_prices import CLUSTER, GI, priced, three
from tests.test_sizing_store import MI, container, rows_of


def in_web() -> Any:
    """2 pods asking 0.5 cores and 512Mi each, using 0.1 cores and 80Mi: wasting
    (0.5 - 0.115) x 2 cores and (512 - 96) x 2 Mi."""
    u = container(pods=2, request={"cpu": 0.5, "memory": 512.0 * MI})
    u.workload = Workload("web", "Deployment", "front")
    return u


def rows(c: Any) -> list[dict[str, Any]]:
    return three(c) + rows_of(in_web(), c=c)


def test_namespaces_cost_their_requests_and_waste_by_hand() -> None:
    c = priced({"cpu": 0.04, "memory": 0.005})
    out = sizing.allocate(rows(c), c)
    assert out["by"] == "namespace" and out["currency"] == "USD"
    shop, web = out["groups"]  # ranked by what their requests cost
    assert (shop["group"], shop["workloads"]) == ("test/shop", 3)  # api, db and idle
    # api 3 x (1 core, 1 GiB), db 0.5 cores and 2 GiB learning, idle 0.25 and 512Mi excluded
    assert shop["cost"]["requests"] == pytest.approx(98.55 + 21.9 + 9.125)
    assert shop["cost"]["waste"] == pytest.approx((2.655 * 0.04 + 2784 / 1024 * 0.005) * 730)
    assert shop["requests"] == pytest.approx(
        {"cpu": 3 + 0.5 + 0.25, "memory": 3 * GI + 2 * GI + GI / 2}
    )
    assert (web["group"], web["workloads"]) == ("test/web", 1)
    assert web["cost"]["requests"] == pytest.approx((1.0 * 0.04 + 1.0 * 0.005) * 730)  # 32.85
    assert web["cost"]["waste"] == pytest.approx((0.77 * 0.04 + 832 / 1024 * 0.005) * 730)
    assert web["waste"] == pytest.approx({"cpu": 0.77, "memory": 832 * MI})


def test_the_groups_add_up_to_the_contracts_totals() -> None:
    c = priced({"cpu": 0.04, "memory": 0.005})
    total = sizing.report(rows(c), CLUSTER, c)["cost"]
    groups = sizing.allocate(rows(c), c)["groups"]
    assert sum(g["cost"]["requests"] for g in groups) == pytest.approx(total["requests"])
    assert sum(g["cost"]["waste"] for g in groups) == pytest.approx(total["waste"])


def test_a_namespace_is_its_clusters() -> None:
    c = priced({"cpu": 0.04, "memory": 0.005})
    other = [
        {**r, "cluster": "eu", "workload": "eu/" + r["workload"].split("/", 1)[1]} for r in three(c)
    ]
    groups = sizing.allocate(three(c) + other, c)["groups"]
    assert sorted(g["group"] for g in groups) == ["eu/shop", "test/shop"]


def test_unpriced_groups_are_in_cores_and_gib_and_rank_a_core_like_4_gib() -> None:
    c = priced()
    big = container(pods=1, request={"cpu": 0.2, "memory": 5.0 * GI})  # 0.2 + 5/4 = 1.45
    big.workload = Workload("mem", "Deployment", "big")
    small = container(pods=1, request={"cpu": 1.0, "memory": 0.0})  # 1.0
    small.workload = Workload("cpu", "Deployment", "small")
    out = sizing.allocate(rows_of(small, big, c=c), c)
    assert out["currency"] is None
    assert [g["group"] for g in out["groups"]] == ["test/mem", "test/cpu"]
    assert all(g["cost"] is None for g in out["groups"])
    assert out["groups"][1]["requests"] == {"cpu": 1.0, "memory": 0.0}


def test_sizing_cost_prints_each_namespace(
    database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from aiops_agent import cli
    from tests.test_sizing_store import lab_fake

    lab_fake(monkeypatch)
    monkeypatch.setenv("AIOPS_DATABASE_URL", database_url)
    c = priced({"cpu": 0.04, "memory": 0.005})
    monkeypatch.setattr(cli, "contract", lambda settings, cid: c)
    assert cli.main(["sizing", "refresh", "--contract", "acme"]) == 0
    capsys.readouterr()
    assert cli.main(["sizing", "cost", "--contract", "acme"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "acme by namespace: requests in its namespaces, not the nodes"
    assert out[1].startswith("test/shop: requests ") and " USD/month, savings available " in out[1]
    assert cli.main(["sizing", "cost", "--contract", "acme", "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["contract"] == "acme" and body["groups"][0]["group"] == "test/shop"


def test_a_namespace_that_wastes_more_but_costs_less_ranks_below() -> None:
    from tests.test_sizing_store import row

    c = priced({"cpu": 0.04, "memory": 0.005})
    sized = row(
        "big",
        namespace="big",
        requests={"cpu": 4.0, "memory": 0.0},
        waste={"cpu": 0.1, "memory": 0.0},
    )
    wasteful = row(
        "w", namespace="w", requests={"cpu": 1.0, "memory": 0.0}, waste={"cpu": 0.9, "memory": 0.0}
    )
    groups = sizing.allocate([wasteful, sized], c)["groups"]
    assert [g["group"] for g in groups] == ["test/big", "test/w"]
