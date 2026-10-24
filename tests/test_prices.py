"""Unit prices (slice 10.1): a Contract's prices turn stored Sizings into a monthly
cost of each Workload's waste and of its requests, computed when shown."""

from typing import Any

import pytest

from aiops_agent import contracts, sizing
from aiops_agent.usage import ContainerUsage, Workload
from tests.conftest import make_contract
from tests.test_sizing_store import MI, container, rows_of

GI = 2**30
CLUSTER = {"test": {"at": 1.0, "error": None, "since": None}}


def priced(prices: dict[str, Any] | None = None, **cluster: Any) -> contracts.Contract:
    data = make_contract().model_dump()
    data["integrations"].append({"name": "prometheus", "url": "http://prometheus"})
    data["sizing"] = {"rules": [{"name": "idle", "policy": "off"}]}
    if prices is not None:
        data["prices"] = prices
    if cluster:
        data["clusters"][0]["prices"] = cluster
    return contracts.build(data)


def named(u: ContainerUsage, name: str) -> ContainerUsage:
    u.workload = Workload("shop", "Deployment", name)
    return u


def three(c: contracts.Contract) -> list[dict[str, Any]]:
    """api: 3 pods asking 1 core and 1 GiB each, using 0.1 cores and 80Mi (sized 115m
    and 96Mi); db: 1 pod still learning, asking 0.5 cores and 2 GiB; idle: excluded,
    1 pod asking 0.25 cores and 512Mi."""
    return rows_of(
        named(container(pods=3), "api"),
        named(container(pods=1, hours=2, request={"cpu": 0.5, "memory": 2.0 * GI}), "db"),
        named(container(pods=1, request={"cpu": 0.25, "memory": 512.0 * MI}), "idle"),
        c=c,
    )


# --- the Contract ------------------------------------------------------------------


def test_prices_validate() -> None:
    c = priced({"cpu": 0.04, "memory": 0.005})
    assert c.prices and c.prices.currency == "USD"
    assert priced({"cpu": 0, "memory": 0}).prices  # already paid for
    for bad in ({"cpu": -0.01, "memory": 0.005}, {"cpu": 0.04, "memory": 0.005, "currency": "usd"}):
        with pytest.raises(ValueError):
            priced(bad)
    with pytest.raises(ValueError, match="set the Contract's prices too"):
        priced(None, cpu=0.04, memory=0.005)
    with pytest.raises(ValueError, match="currency"):
        priced({"cpu": 0.04, "memory": 0.005}, cpu=0.05, memory=0.006, currency="EUR")


def test_a_clusters_own_prices_win() -> None:
    c = priced({"cpu": 0.04, "memory": 0.005}, cpu=0.05, memory=0.006)
    own = c.price("test")
    assert own and (own.cpu, own.memory) == (0.05, 0.006)
    contracts_own = priced({"cpu": 0.04, "memory": 0.005}).price("test")
    assert contracts_own and (contracts_own.cpu, contracts_own.memory) == (0.04, 0.005)
    assert priced().price("test") is None


# --- what is stored ----------------------------------------------------------------


def test_every_row_stores_its_requests_and_pods_whatever_its_state() -> None:
    rows = {r["name"]: r for r in three(priced())}
    assert {n: r["state"] for n, r in rows.items()} == {
        "api": "ready",
        "db": "learning",
        "idle": "excluded",
    }
    assert rows["db"]["requests"] == {"cpu": 0.5, "memory": 2.0 * GI} and rows["db"]["pods"] == 1
    assert rows["idle"]["requests"] == {"cpu": 0.25, "memory": 512.0 * MI}
    assert rows["idle"]["pods"] == 1


# --- money, by hand ----------------------------------------------------------------


def test_waste_and_requests_cost_a_month_by_hand() -> None:
    c = priced({"cpu": 0.04, "memory": 0.005, "currency": "EUR"})
    out = sizing.report(three(c), CLUSTER, c)
    (api,) = out["workloads"]  # only ready Workloads are ranked
    # waste: (1 - 0.115) cores x 3 pods, (1024 - 96) Mi x 3 pods
    assert api["waste"] == pytest.approx({"cpu": 2.655, "memory": 2784 * MI})
    waste = (2.655 * 0.04 + 2784 / 1024 * 0.005) * 730  # 87.45
    requests = (3 * 0.04 + 3 * 0.005) * 730  # 98.55
    assert api["cost"] == pytest.approx({"waste": waste, "requests": requests})
    db = (0.5 * 0.04 + 2 * 0.005) * 730  # 21.90, still learning
    idle = (0.25 * 0.04 + 0.5 * 0.005) * 730  # 9.125, excluded
    assert out["currency"] == "EUR"
    assert out["cost"] == pytest.approx({"waste": waste, "requests": requests + db + idle})


def test_a_clusters_prices_apply_to_its_rows() -> None:
    c = priced({"cpu": 0.04, "memory": 0.005}, cpu=0.08, memory=0.01)
    (api,) = sizing.report(three(c), CLUSTER, c)["workloads"]
    assert api["cost"]["requests"] == pytest.approx((3 * 0.08 + 3 * 0.01) * 730)


def test_a_row_stored_before_prices_counts_its_ready_requests() -> None:
    c = priced({"cpu": 0.04, "memory": 0.005})
    old = [{k: v for k, v in r.items() if k != "requests"} for r in three(c)]
    out = sizing.report(old, CLUSTER, c)
    assert out["cost"]["requests"] == pytest.approx((3 * 0.04 + 3 * 0.005) * 730)


def test_with_prices_the_ranking_is_by_money() -> None:
    """2 cores against 12 GiB: by the 4 GiB weighting memory-heavy wastes more; with
    memory nearly free, cpu-heavy costs more."""
    cpu_heavy = named(container(pods=1, request={"cpu": 2.115, "memory": 96.0 * MI}), "cpu-heavy")
    mem_heavy = named(
        container(pods=1, request={"cpu": 0.115, "memory": 12.0 * GI + 96 * MI}), "mem"
    )
    unpriced = priced()
    by_weight = sizing.report(rows_of(cpu_heavy, mem_heavy, c=unpriced), CLUSTER, unpriced)
    assert [w["name"] for w in by_weight["workloads"]] == ["mem", "cpu-heavy"]
    cheap_memory = priced({"cpu": 0.04, "memory": 0.0001})
    by_money = sizing.report(rows_of(cpu_heavy, mem_heavy, c=cheap_memory), CLUSTER, cheap_memory)
    assert [w["name"] for w in by_money["workloads"]] == ["cpu-heavy", "mem"]


def test_without_prices_nothing_changes() -> None:
    c = priced()
    out = sizing.report(three(c), CLUSTER, c)
    assert "currency" not in out and "cost" not in out
    assert "cost" not in out["workloads"][0]
    assert out == sizing.report(three(c), CLUSTER)


# --- where it shows ----------------------------------------------------------------


def test_the_digest_says_the_money() -> None:
    c = priced({"cpu": 0.04, "memory": 0.005})
    now = sizing.report(three(c), CLUSTER, c)
    week = sizing.report(three(c)[:1], CLUSTER, c) | {"cost": {"waste": 80.0, "requests": 90.0}}
    text = sizing.digest_text("acme", now, week)
    assert "Waste: 87.45 USD/month (+7.45 USD vs 7 days ago): 2.66 cores, 2.72 GiB" in text
    assert "Requests cost 129.58 USD/month." in text
    assert "1. `test/shop/Deployment/api`: 87.45 USD/month (2.66 cores, 2.72 GiB)" in text


def test_an_unpriced_digest_keeps_cores_and_gib() -> None:
    c = priced()
    now = sizing.report(three(c), CLUSTER, c)
    text = sizing.digest_text("acme", now, now)
    assert "Waste: 2.66 cores, 2.72 GiB (+0.00 cores, +0.00 GiB vs 7 days ago)" in text
    assert "USD" not in text and "Requests cost" not in text


def test_sizing_waste_prints_the_money(
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
    assert cli.main(["sizing", "waste", "--contract", "acme"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[1].startswith("acme: waste ") and " USD/month (" in out[1]
    assert "; requests cost " in out[1]
    api = next(line for line in out if line.startswith("test/shop/Deployment/api: "))
    # 0.885 cores and 928Mi wasted of 1 core and 1 GiB asked, 1 pod, by hand
    assert api == (
        "test/shop/Deployment/api: 29.15 USD/month of 32.85 USD/month, "
        "0.89 cores, 0.91 GiB, avg 1 pods"
    )
