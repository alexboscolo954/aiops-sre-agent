"""Savings and compare periods (slice 10.3a): each group's requests and available
Savings (the waste's cost) now against each cluster's latest run N days ago, both at
today's prices, comparing only what both sides know."""

import json
from typing import Any

import pytest

from aiops_agent import contracts, sizing
from aiops_agent.store import Store, connect
from tests.test_sizing_store import NOW, H, row, stored
from tests.test_teams import allocated, r

DAY = 24 * H
CORE = 0.05 * 730  # a core for a month at 0.05 per vCPU-hour: 36.5


@pytest.fixture
async def store(database_url: str) -> Any:
    async with connect(database_url) as pool:
        s = Store(pool)
        await s.migrate()
        yield s


def wasting(row: dict[str, Any], cores: float) -> dict[str, Any]:
    return {**row, "waste": {"cpu": cores, "memory": 0.0}}


@pytest.mark.anyio
async def test_each_groups_change_by_hand_adding_up_to_the_contracts(store: Store) -> None:
    c = allocated()
    both = {"test": None, "eu": None}
    await stored(
        store,
        "acme",
        NOW,
        both,
        wasting(r("test", "shop", "api", 3.0), 2.0),
        r("test", "pay", "old", 1.0),  # gone since
        r("eu", "shop", "web", 1.0),
    )
    await stored(
        store,
        "acme",
        NOW + DAY,
        both,
        wasting(r("test", "shop", "api", 2.0), 1.0),
        r("eu", "shop", "web", 1.0),
        r("eu", "shop", "new", 2.0),  # new since: a real new cost
    )
    out = await sizing.cost(store, c, "namespace", NOW + DAY, DAY)
    groups = {g["group"]: g for g in out["groups"]}
    assert groups["test/shop"]["change"]["cost"] == pytest.approx(
        {"requests": -CORE, "waste": -CORE}
    )
    assert groups["test/shop"]["change"]["requests"] == pytest.approx({"cpu": -1.0, "memory": 0.0})
    assert groups["eu/shop"]["change"]["cost"] == pytest.approx(
        {"requests": 2 * CORE, "waste": CORE}
    )
    gone = groups["test/pay"]  # listed after the ranked groups, with its whole drop
    assert out["groups"][-1] is gone and gone["workloads"] == 0
    assert gone["cost"] == {"requests": 0.0, "waste": 0.0}
    assert gone["change"]["cost"] == pytest.approx({"requests": -CORE, "waste": -CORE})
    total = out["compare"]["change"]["cost"]
    assert total["requests"] == pytest.approx(
        sum(g["change"]["cost"]["requests"] for g in groups.values())
    )
    assert total["waste"] == pytest.approx(
        sum(g["change"]["cost"]["waste"] for g in groups.values())
    )
    assert total == pytest.approx({"requests": 0.0, "waste": -CORE})
    assert out["compare"]["since"] == NOW
    assert out["compare"]["clusters"] == {
        "eu": {"at": NOW, "oldest": NOW},
        "test": {"at": NOW, "oldest": NOW},
    }
    assert out["total"]["cost"] == pytest.approx({"requests": 5 * CORE, "waste": 3 * CORE})


@pytest.mark.anyio
async def test_both_sides_are_priced_today_so_a_new_price_changes_nothing(store: Store) -> None:
    """The same rows then and now: no change whatever the price, as 10.1 prices history."""
    for at in (NOW, NOW + DAY):
        await stored(store, "acme", at, {"test": None, "eu": None}, r("test", "shop", "api", 3.0))
    for price in (0.05, 0.5):
        data = allocated().model_dump()
        data["prices"]["cpu"] = price
        c = contracts.build(data)
        out = await sizing.cost(store, c, "namespace", NOW + DAY, DAY)
        assert out["groups"][0]["cost"]["requests"] == pytest.approx(3 * price * 730)
        assert out["groups"][0]["change"]["cost"] == pytest.approx({"requests": 0.0, "waste": 0.0})


@pytest.mark.anyio
async def test_no_run_that_old_names_the_oldest_and_compares_nothing(store: Store) -> None:
    await stored(store, "acme", NOW, {"test": None, "eu": None}, r("test", "shop", "api", 3.0))
    out = await sizing.cost(store, allocated(), "namespace", NOW + H, 30 * DAY)
    assert out["compare"]["clusters"]["test"] == {"at": None, "oldest": NOW}
    assert out["compare"]["change"]["cost"] == {"requests": 0.0, "waste": 0.0}
    (g,) = out["groups"]
    assert g["change"]["cost"] == {"requests": 0.0, "waste": 0.0}  # left out, not "new"


@pytest.mark.anyio
async def test_a_cluster_with_no_run_that_old_is_left_out_of_both_sides(store: Store) -> None:
    """eu was read first a day later: its requests aren't a change, test's are."""
    await stored(store, "acme", NOW, {"test": None, "eu": "boom"}, r("test", "shop", "api", 3.0))
    await stored(
        store,
        "acme",
        NOW + DAY,
        {"test": None, "eu": None},
        r("test", "shop", "api", 2.0),
        r("eu", "shop", "web", 4.0),
    )
    out = await sizing.cost(store, allocated(), "namespace", NOW + DAY, DAY)
    assert out["compare"]["clusters"]["eu"] == {
        "at": None,
        "oldest": NOW + DAY,
    }  # a failed read isn't one
    assert out["compare"]["change"]["cost"]["requests"] == pytest.approx(-CORE)
    groups = {g["group"]: g for g in out["groups"]}
    assert groups["eu/shop"]["change"]["cost"]["requests"] == 0.0


@pytest.mark.anyio
async def test_requests_unknown_then_are_left_out_of_both_sides(store: Store) -> None:
    """A learning row stored before 10.1 has no requests: it would look like a new cost."""
    before_10_1 = {**r("test", "shop", "db", 0.0), "state": "learning"}
    del before_10_1["requests"], before_10_1["waste"]
    await stored(
        store, "acme", NOW, {"test": None, "eu": None}, before_10_1, r("test", "shop", "api", 1.0)
    )
    await stored(
        store,
        "acme",
        NOW + DAY,
        {"test": None, "eu": None},
        {**r("test", "shop", "db", 4.0), "state": "learning"},
        r("test", "shop", "api", 1.0),
    )
    out = await sizing.cost(store, allocated(), "namespace", NOW + DAY, DAY)
    assert out["compare"]["left_out"] == ["test/shop/Deployment/db/app"]
    assert out["compare"]["change"]["cost"]["requests"] == pytest.approx(0.0)
    assert out["groups"][0]["cost"]["requests"] == pytest.approx(5 * CORE)  # now shows it all


@pytest.mark.anyio
async def test_rows_stored_without_labels_are_left_out_when_the_grouping_reads_them(
    store: Store,
) -> None:
    """Before 10.2b no row had labels: by team, every Workload would seem to move from
    (no team) to its team. By namespace they compare as usual."""
    await stored(store, "acme", NOW, {"test": None, "eu": None}, r("test", "shop", "web", 2.0))
    await stored(
        store,
        "acme",
        NOW + DAY,
        {"test": None, "eu": None},
        r("test", "shop", "web", 1.0, team="storefront"),
    )
    by_team = await sizing.cost(store, allocated(), "team", NOW + DAY, DAY)
    assert by_team["compare"]["left_out"] == ["test/shop/Deployment/web/app"]
    assert [g["group"] for g in by_team["groups"]] == ["storefront"]  # no "(no team)" gone since
    assert by_team["compare"]["change"]["cost"]["requests"] == 0.0
    by_label = await sizing.cost(store, allocated(), "label:team", NOW + DAY, DAY)
    assert by_label["compare"]["left_out"] == ["test/shop/Deployment/web/app"]
    by_ns = await sizing.cost(store, allocated(), "namespace", NOW + DAY, DAY)
    assert by_ns["compare"]["left_out"] == []
    assert by_ns["compare"]["change"]["cost"]["requests"] == pytest.approx(-CORE)
    # Team rules on namespaces only read no labels: nothing is left out
    plain = allocated({"teams": [{"team": "shop", "namespace": "shop"}]})
    by_rule = await sizing.cost(store, plain, "team", NOW + DAY, DAY)
    assert by_rule["compare"]["left_out"] == []


@pytest.mark.anyio
async def test_a_cluster_whose_pods_got_the_labels_since_is_left_out(store: Store) -> None:
    """The Contract listed `team` a day before kube-state-metrics exported it: the old
    run stored empty labels. eu had them both times and compares as usual."""
    both = {"test": None, "eu": None}
    await stored(
        store,
        "acme",
        NOW,
        both,
        {**r("test", "shop", "web", 2.0), "labels": {}},
        r("eu", "shop", "api", 2.0, team="storefront"),
    )
    await stored(
        store,
        "acme",
        NOW + DAY,
        both,
        r("test", "shop", "web", 1.0, team="storefront"),
        r("eu", "shop", "api", 1.0, team="storefront"),
    )
    by_team = await sizing.cost(store, allocated(), "team", NOW + DAY, DAY)
    assert by_team["compare"]["left_out"] == ["test/shop/Deployment/web/app"]
    assert by_team["compare"]["change"]["cost"]["requests"] == pytest.approx(-CORE)  # eu's
    by_ns = await sizing.cost(store, allocated(), "namespace", NOW + DAY, DAY)
    assert by_ns["compare"]["left_out"] == []
    assert by_ns["compare"]["change"]["cost"]["requests"] == pytest.approx(-2 * CORE)
    assert sizing._label_keys(allocated(), "namespace") == []  # even a label named so


@pytest.mark.anyio
async def test_unpriced_changes_are_in_cores_and_gib(store: Store) -> None:
    await stored(store, "acme", NOW, {"test": None, "eu": None}, r("test", "shop", "api", 3.0))
    await stored(
        store, "acme", NOW + DAY, {"test": None, "eu": None}, r("test", "shop", "api", 1.0)
    )
    out = await sizing.cost(store, allocated(priced=False), "namespace", NOW + DAY, DAY)
    (g,) = out["groups"]
    assert g["change"]["cost"] is None and out["compare"]["change"]["cost"] is None
    assert g["change"]["requests"] == {"cpu": -2.0, "memory": 0.0}
    assert out["total"]["cost"] is None and out["total"]["requests"]["cpu"] == 1.0


@pytest.mark.anyio
async def test_the_oldest_run_is_the_contracts_own(store: Store) -> None:
    """bank's old runs, and acme's failed reads, never date acme's comparison."""
    await stored(store, "bank", NOW - 9 * DAY, {"test": None}, row("api"))
    await stored(store, "acme", NOW - 5 * DAY, {"test": "boom"})
    await stored(store, "acme", NOW, {"test": None}, row("api"))
    assert await store.first_sizings("acme", {"test", "eu"}) == {"test": NOW}
    assert await store.first_sizings("bank", {"test"}) == {"test": NOW - 9 * DAY}
    assert await store.first_sizings("acme", {"eu"}) == {}
    out = await sizing.cost(store, allocated(), "namespace", NOW + H, 7 * DAY)
    assert out["compare"]["clusters"]["test"] == {"at": None, "oldest": NOW}


def test_sizing_cost_compares_and_refuses_a_bad_ago(
    database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import asyncio

    from aiops_agent import cli

    async def seed() -> None:
        async with connect(database_url) as pool:
            s = Store(pool)
            await s.migrate()
            both = {"test": None, "eu": None}
            await stored(
                s, "acme", NOW, both, r("test", "shop", "api", 3.0), r("eu", "shop", "web", 1.0)
            )
            await stored(
                s, "acme", NOW + DAY, {"test": None, "eu": "boom"}, r("test", "shop", "api", 2.0)
            )

    asyncio.run(seed())
    monkeypatch.setenv("AIOPS_DATABASE_URL", database_url)
    monkeypatch.setattr(cli, "contract", lambda settings, cid: allocated())
    monkeypatch.setattr("time.time", lambda: NOW + DAY + H)
    assert cli.main(["sizing", "cost", "--contract", "acme", "--compare", "1d"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[1] == (
        "test/shop: requests 73.00 USD/month (-36.50 USD/month), "
        "savings available 36.50 USD/month (+0.00 USD/month), 1 Workloads"
    )
    assert out[2].startswith("eu/shop: requests 36.50 USD/month (+0.00 USD/month)")
    assert out[3].startswith("total: requests 109.50 USD/month (-36.50 USD/month)")
    assert "test: compared with its run of 1972-09-27 00:00 UTC" in out
    assert cli.main(["sizing", "cost", "--contract", "acme", "--compare", "soon"]) == 2
    assert "--compare: " in capsys.readouterr().err
    assert cli.main(["sizing", "cost", "--contract", "acme", "--compare", "30d"]) == 0
    old = capsys.readouterr().out.splitlines()
    assert "test: no run that old, oldest 1972-09-27 00:00 UTC; left out" in old
    assert cli.main(["sizing", "cost", "--contract", "acme", "--compare", "30d", "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["compare"]["clusters"]["test"] == {"at": None, "oldest": NOW}
    assert cli.main(["sizing", "cost", "--contract", "acme"]) == 0
    assert "(" not in capsys.readouterr().out  # no comparison asked
