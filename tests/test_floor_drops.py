"""Realized Floor savings (slice 14.1c): an HPA's minimum lowered while the Hub showed a
Floor below it is a drop, down to that Floor and no further; worth the replicas it no longer
holds at the pod's requests, inside the Realized Savings; a rise takes it back."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from squero import cli, sizing, usage
from squero.config import Settings
from squero.contracts import Contract
from squero.store import Store, connect
from squero.usage import Bounds, Workload
from tests.test_floors import KEY, limits, scaled_fake
from tests.test_floors import hourly as hours_of
from tests.test_realized import PRICES, hourly, priced, sized
from tests.test_sizing_store import prometheus_contract, store  # noqa: F401
from tests.test_usage import _prom
from tests.test_webapp import VIEW, app_dir, hub  # noqa: F401

DAY = 86_400.0
H = 3600.0
GI = 2**30
NOW = 1000 * DAY
API = Workload("shop", "Deployment", "api")


def shown(minimum: float | None = 6.0, floor: int = 3, **changes: Any) -> dict[str, Any]:
    """A Floor as the last run stored it: ready, below its HPA's minimum."""
    where = {"cluster": "test", "namespace": "shop", "kind": "Deployment", "name": "api"}
    f = {**where, "workload": "test/shop/Deployment/api", "state": "ready"}
    return {**f, "minimum": minimum, "floor": floor, "risks": []} | changes


def read(minimum: float | None, *more: Bounds, cluster: str = "test") -> dict[str, Any]:
    """The bounds a run read: the Workload's HPA with this minimum."""
    return {cluster: {API: [Bounds("api", minimum, 9.0), *more]}}


async def drops(store: Store, cid: str = "acme") -> list[tuple[float, float, float, float]]:  # noqa: F811
    found = await store.floor_drops(cid)
    return [(e["at"], e["before"], e["after"], e["floor"]) for e in found]


async def realize(
    store: Store,  # noqa: F811
    at: float,
    last: dict[str, Any] | None,
    now: dict[str, Any],
    c: Contract | None = None,
) -> None:
    await sizing.realize_floors(store, c or prometheus_contract(), at, [last] if last else [], now)


# --- a drop ----------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_minimum_lowered_under_a_floor_shown_below_it_is_a_drop(store: Store) -> None:  # noqa: F811
    await realize(store, NOW, shown(6.0, 3), read(4.0))
    assert await drops(store) == [(NOW, 6.0, 4.0, 3.0)]
    (e,) = await store.floor_drops("acme")
    assert (e["cluster"], e["namespace"], e["kind"], e["name"]) == ("test", *KEY)
    await realize(store, NOW, shown(6.0, 3), read(4.0))  # the same run again: once
    assert await drops(store) == [(NOW, 6.0, 4.0, 3.0)]


@pytest.mark.anyio
async def test_a_drop_counts_down_to_the_floor_and_no_further(store: Store) -> None:  # noqa: F811
    """From 6 to 1 with a Floor of 3: three replicas are the Hub's advice, not five."""
    await realize(store, NOW, shown(6.0, 3), read(1.0))
    assert await drops(store) == [(NOW, 6.0, 3.0, 3.0)]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("last", "now"),
    [
        (shown(6.0, 3), read(6.0)),  # not lowered
        (shown(6.0, 3), read(7.0)),  # raised
        (shown(6.0, 6), read(4.0)),  # at its Floor then: lowering it was not the advice
        (shown(6.0, 8), read(4.0)),  # below its Floor then
        (shown(6.0, 3, state="learning"), read(4.0)),  # no Floor shown yet
        (shown(None, 3, state="none"), read(4.0)),
        (None, read(4.0)),  # no Floor stored for it: before this slice, or a new HPA
        (shown(6.0, 3), read(None)),  # its minimum not known now
        (shown(6.0, 3), read(4.0, Bounds("b", 2.0, 9.0))),  # two HPAs now
        (shown(6.0, 3, name="web"), read(4.0)),  # another Workload's Floor
        (shown(6.0, 3, cluster="edge"), read(4.0)),  # another cluster's
    ],
)
async def test_what_is_no_drop(
    store: Store,  # noqa: F811
    last: dict[str, Any] | None,
    now: dict[str, Any],
) -> None:
    await realize(store, NOW, last, now)
    assert await drops(store) == []


# --- taken back ------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_minimum_raised_again_takes_the_drop_back(store: Store) -> None:  # noqa: F811
    await realize(store, NOW, shown(6.0, 3), read(4.0))
    await realize(store, NOW + H, shown(4.0, 3), read(5.0))  # partway
    assert await drops(store) == [(NOW, 6.0, 5.0, 3.0)]
    await realize(store, NOW + 2 * H, shown(5.0, 3), read(4.0))  # down again: a new drop
    assert await drops(store) == [(NOW, 6.0, 5.0, 3.0), (NOW + 2 * H, 5.0, 4.0, 3.0)]
    await realize(store, NOW + 3 * H, shown(4.0, 3), read(6.0))  # back at the first
    assert await drops(store) == []
    await realize(store, NOW + 4 * H, shown(6.0, 3), read(4.0))
    await realize(store, NOW + 5 * H, shown(4.0, 3), read(8.0))  # past it
    assert await drops(store) == []


@pytest.mark.anyio
async def test_a_rise_takes_the_newest_drop_first_and_never_below_what_it_counted(
    store: Store,  # noqa: F811
) -> None:
    """6 to 4, then 4 to 2 (counted to its Floor of 3): a minimum back at 3 changes
    nothing, at 5 the second is gone and the first is one replica."""
    await realize(store, NOW, shown(6.0, 3), read(4.0))
    await realize(store, NOW + H, shown(4.0, 3), read(2.0))
    assert await drops(store) == [(NOW, 6.0, 4.0, 3.0), (NOW + H, 4.0, 3.0, 3.0)]
    await realize(store, NOW + 2 * H, shown(2.0, 3), read(3.0))
    assert await drops(store) == [(NOW, 6.0, 4.0, 3.0), (NOW + H, 4.0, 3.0, 3.0)]
    await realize(store, NOW + 3 * H, shown(3.0, 3), read(5.0))
    assert await drops(store) == [(NOW, 6.0, 5.0, 3.0)]


@pytest.mark.anyio
async def test_a_drop_ends_with_its_hpa_and_survives_what_was_not_read(store: Store) -> None:  # noqa: F811
    async def fresh() -> None:
        await store.save_floor_drops(
            "acme", [], {}, {e["id"] for e in await store.floor_drops("acme")}
        )
        await realize(store, NOW, shown(6.0, 3), read(4.0))

    await fresh()
    await realize(store, NOW + H, None, {"edge": {}})  # its cluster not read this run
    await realize(store, NOW + H, None, read(None))  # its minimum not known
    assert len(await drops(store)) == 1
    await realize(store, NOW + H, None, {"test": {}})  # read, its HPA gone
    assert await drops(store) == []
    await fresh()
    await realize(store, NOW + H, None, read(4.0, Bounds("b", 2.0, 9.0)))  # a second HPA
    assert await drops(store) == []
    await fresh()
    other = {"test": {Workload("shop", "Deployment", "web"): [Bounds("web", 1.0, 9.0)]}}
    await realize(store, NOW + H, None, other)  # only another Workload's HPA is left
    assert await drops(store) == []


@pytest.mark.anyio
async def test_a_contracts_drops_never_reach_another(store: Store) -> None:  # noqa: F811
    bank = prometheus_contract("bank")
    await realize(store, NOW, shown(6.0, 3), read(4.0))
    await realize(store, NOW, shown(9.0, 2), read(5.0), bank)
    assert await drops(store) == [(NOW, 6.0, 4.0, 3.0)]
    assert await drops(store, "bank") == [(NOW, 9.0, 5.0, 2.0)]
    await realize(store, NOW + H, None, {"test": {}})  # acme's HPA gone: bank's stays
    assert await drops(store) == [] and len(await drops(store, "bank")) == 1
    (theirs,) = await store.floor_drops("bank")
    await store.save_floor_drops("acme", [], {theirs["id"]: 8.0}, {theirs["id"]})  # not acme's
    assert await drops(store, "bank") == [(NOW, 9.0, 5.0, 2.0)]


@pytest.mark.anyio
async def test_a_run_compares_with_the_floors_the_last_run_showed(
    store: Store,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end: a run shows a Floor of 2 under a minimum of 4; the next reads a minimum
    of 2 and stores the drop, then its own Floors."""
    fake = scaled_fake(current=30.0)  # needs 1.8 now
    fake.series = [s for s in fake.series if "_spec_min_replicas" not in s["__name__"]]
    limits(fake, 4.0, None)
    monkeypatch.setattr(usage, "Prom", lambda t: _prom(fake, t))
    c = prometheus_contract()
    await store.save_needs(c.id, "test", {KEY: hours_of([1.2] * 30)})
    assert await sizing.store_run(store, c, NOW) is not None
    (f,) = await store.latest_floors(c.id, {"test"})
    assert (f["floor"], f["minimum"]) == (2, 4.0) and await drops(store) == []
    fake.series = [s for s in fake.series if "_spec_min_replicas" not in s["__name__"]]
    limits(fake, 2.0, None)
    assert await sizing.store_run(store, c, NOW + H) is not None
    assert await drops(store) == [(NOW + H, 4.0, 2.0, 2.0)]
    (f,) = await store.latest_floors(c.id, {"test"})
    assert f["minimum"] == 2.0 and f["at"] == NOW + H
    assert await sizing.store_run(store, c, NOW + 2 * H) is not None  # nothing new
    assert await drops(store) == [(NOW + H, 4.0, 2.0, 2.0)]


# --- what it is worth ------------------------------------------------------------------


async def dropped(
    store: Store,  # noqa: F811
    c: Contract,
    at: float,
    needs: dict[float, float],
    before: float = 6.0,
    after: float = 3.0,
) -> None:
    """The Workload's latest rows (app asking 1 core and 1 GiB, a sidecar 200m), a drop
    seen at `at` and its stored Needs."""
    side = sized(0.2, None, name="api", memory=0.0)
    side["container"], side["workload"] = "sidecar", "test/shop/Deployment/api/sidecar"
    await hourly(store, c, at, sized(1.0, 0.115), side)
    where = dict(zip(("namespace", "kind", "name"), KEY, strict=True))
    drop = {"cluster": "test", **where, "at": at, "before": before, "after": after, "floor": 3}
    await store.save_floor_drops(c.id, [drop], {}, set())
    await store.save_needs(c.id, "test", {KEY: needs})


@pytest.mark.anyio
async def test_a_drop_is_worth_the_replicas_no_longer_held_at_the_pods_requests(
    store: Store,  # noqa: F811
) -> None:
    """A minimum from 6 to 3, ten hours ago. Four hours needed 1 (3 run, 3 fewer), four
    needed 4.5 (5 run, 1 fewer), two needed 8 (nothing saved): 1.6 replicas on average,
    each asking 1.2 cores and 1 GiB as its containers ask now."""
    c = priced(PRICES)
    needs = hours_of([1.0] * 4 + [4.5] * 4 + [8.0] * 2, last=NOW + 9 * H)
    await dropped(store, c, NOW, needs)
    out = await sizing.savings(store, c, NOW + 10 * H)
    (d,) = out["floors"]
    assert d["workload"] == "test/shop/Deployment/api"
    assert (d["at"], d["before"], d["after"], d["floor"], d["replicas"]) == (
        NOW,
        6.0,
        3.0,
        3.0,
        1.6,
    )
    assert d["saved"] == {"cpu": pytest.approx(1.6 * 1.2), "memory": pytest.approx(1.6 * GI)}
    rate = (1.6 * 1.2 * 0.04 + 1.6 * 0.005) * 730
    assert d["cost"] == {"rate": pytest.approx(rate), "accrued": pytest.approx(rate / 730 * 10)}
    assert out["drops"] == []  # no request was lowered: the totals are the Floor's
    assert out["rate"] == d["saved"] and out["week"] == d["saved"]
    assert out["accrued"]["cpu"] == pytest.approx(1.6 * 1.2 * 10)
    assert out["cost"] == {
        "rate": pytest.approx(rate),
        "accrued": pytest.approx(rate / 730 * 10),
        "week": pytest.approx(rate),
    }
    plain = await sizing.savings(store, prometheus_contract(), NOW + 10 * H)
    assert plain["floors"][0]["cost"] is None and plain["cost"] is None
    assert plain["rate"] == d["saved"]


@pytest.mark.anyio
async def test_only_complete_hours_since_the_drop_in_the_last_week_count(store: Store) -> None:  # noqa: F811
    """A drop seen at 00:20: the hour it was seen in counts once complete; the hours
    before it, the hour under way and those over a week old do not."""
    c = priced(PRICES)
    seen = NOW + 1200
    needs = {NOW - H: 1.0, NOW: 4.5, NOW + H: 8.0, NOW + 2 * H: 1.0}
    await dropped(store, c, seen, needs)
    at = NOW + 2.5 * H  # the hour from 02:00 is under way
    (d,) = (await sizing.savings(store, c, at))["floors"]
    assert d["replicas"] == 0.5  # 1 fewer and none: the hours from 00:00 and 01:00
    (d,) = (await sizing.savings(store, c, NOW + 0.5 * H))["floors"]
    assert d["replicas"] == 0 and d["saved"] == {"cpu": 0.0, "memory": 0.0}  # none stored yet
    late = NOW + 8 * DAY
    await store.save_needs(c.id, "test", {KEY: hours_of([4.5] * 24, last=late - H)})
    await hourly(store, c, late - H, sized(1.0, 0.115))
    out = await sizing.savings(store, c, late)
    (d,) = out["floors"]
    assert d["replicas"] == 1.0  # the last day's 4.5s; the 1.0s of a week ago are out
    assert out["week"] == {"cpu": 0.0, "memory": 0.0}  # the drop is over a week old
    assert out["accrued"]["cpu"] == pytest.approx(1.0 * 1.0 * (late - seen) / H)


@pytest.mark.anyio
async def test_a_drop_adds_to_the_request_drops_and_needs_its_workloads_rows(store: Store) -> None:  # noqa: F811
    c = priced(PRICES)
    await hourly(store, c, NOW - H, sized(1.0, 0.115))
    await dropped(store, c, NOW, hours_of([1.0] * 5, last=NOW + 4 * H))
    await hourly(store, c, NOW + H, sized(0.115, 0.115))  # the request lowered to its Sizing
    await store.save_needs(c.id, "edge", {KEY: hours_of([9.0] * 5, last=NOW + 4 * H)})
    out = await sizing.savings(store, c, NOW + 5 * H)
    (request,), (minimum,) = out["drops"], out["floors"]
    assert minimum["replicas"] == 3.0 and minimum["saved"]["cpu"] == pytest.approx(3 * 0.115)
    assert out["rate"]["cpu"] == pytest.approx(request["saved"] + 3 * 0.115)
    assert out["cost"]["rate"] == pytest.approx(request["cost"]["rate"] + minimum["cost"]["rate"])
    assert out["cost"]["week"] == pytest.approx(out["cost"]["rate"])
    assert sizing.realized_line(out) is not None
    gone = prometheus_contract("bank")
    await store.save_floor_drops(
        gone.id, [{**shown(), "at": NOW, "before": 6, "after": 3}], {}, set()
    )
    theirs = await sizing.savings(store, gone, NOW + 5 * H)
    assert theirs["floors"] == [] and theirs["rate"] == {"cpu": 0.0, "memory": 0.0}  # no rows


# --- shown -----------------------------------------------------------------------------


def test_sizing_savings_prints_each_lowered_minimum(
    database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    c = priced(PRICES)

    async def seed() -> None:
        async with connect(database_url) as pool:
            s = Store(pool)
            await s.migrate()
            await dropped(s, c, NOW, hours_of([1.0] * 10, last=NOW + 9 * H))

    asyncio.run(seed())
    monkeypatch.setenv("SQUERO_DATABASE_URL", database_url)
    monkeypatch.setattr(cli, "contract", lambda settings, cid: c)
    monkeypatch.setattr("time.time", lambda: NOW + 10 * H)
    assert cli.main(["sizing", "savings", "--contract", "acme"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "acme: realized Savings 116.07 USD/month, 1.59 USD so far; "
        "116.07 USD/month from this week's",
        "test/shop/Deployment/api HPA minimum: 6 to 3 (Floor 3) since 1972-09-27 00:00 UTC, "
        "3 replicas fewer on average: 116.07 USD/month, 1.59 USD so far",
    ]


def test_the_cost_route_lists_the_lowered_minimums_in_the_realized_savings(
    settings: Settings,
    fake_cluster: Any,
    database_url: str,
    app_dir: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = prometheus_contract()

    async def seed() -> None:
        async with connect(database_url) as pool:
            s = Store(pool)
            await s.migrate()
            await dropped(s, c, NOW, hours_of([1.0] * 10, last=NOW + 9 * H))
            theirs = {**shown(), "at": NOW, "before": 9, "after": 2}
            await s.save_floor_drops("bank", [theirs], {}, set())

    asyncio.run(seed())
    monkeypatch.setattr("time.time", lambda: NOW + 10 * H)
    with hub(settings, fake_cluster, database_url) as client:
        body = client.get("/api/v1/contracts/acme/cost", headers=VIEW).json()
    (d,) = body["realized"]["floors"]
    assert (d["workload"], d["before"], d["after"], d["replicas"]) == (
        "test/shop/Deployment/api",
        6,
        3,
        3,
    )
    assert (
        body["realized"]["rate"]["cpu"] == pytest.approx(3 * 1.2)
        and body["realized"]["drops"] == []
    )
