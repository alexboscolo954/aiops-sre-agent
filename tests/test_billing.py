"""AWS bills (slice 10.5a): a billed cluster's tagged EC2 compute, read from Cost Explorer
a day at a time, set beside what its node-hours cost at the Hub's prices. The estimate
is node capacity-hours times the cluster's CPU and GiB prices; the gap is its distance
from the bill as a fraction of the bill, within 5% or flagged."""

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from aiops_agent import billing, contracts, usage
from aiops_agent.config import Settings
from aiops_agent.store import Store, connect
from tests.conftest import make_contract
from tests.fake_prometheus import FakePrometheus
from tests.test_api import client
from tests.test_sizing_store import NOW, H
from tests.test_usage import _prom

GI = 2**30
TAG = "aiops-cluster=kind"
DAYS = [
    "1972-09-19",
    "1972-09-20",
    "1972-09-21",
    "1972-09-22",
    "1972-09-23",
    "1972-09-24",
    "1972-09-25",
]
AWS = {
    "name": "aws",
    "regions": ["us-east-1"],
    "access_key_id": "AKIAIOSFODNN7EXAMPLE",
    "secret_access_key_secret": "aws-key",
}
SECRET = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
# 2 vCPU and 8 GiB for the 7 days (168 h): 336 vCPU-hours and 1344 GiB-hours, which at
# 0.03 and 0.004 per hour cost 10.08 + 5.376 = 15.456
ESTIMATE = 336 * 0.03 + 1344 * 0.004


def billed(contract_id: str = "acme", **cluster: Any) -> contracts.Contract:
    data = make_contract(contract_id=contract_id).model_dump()
    data["integrations"] += [{"name": "prometheus", "url": "http://prometheus"}, AWS]
    data["prices"] = {"currency": "USD", "cpu": 0.03, "memory": 0.004}
    data["clusters"][0]["billing"] = {"tag": TAG}
    data["clusters"][0].update(cluster)
    return contracts.build(data, secrets={"aws-key": SecretStr(SECRET)})


def nodes(fake: FakePrometheus, hours: int = 168) -> None:
    fake.add("kube_node_status_capacity", [2.0] * hours, node="n1", resource="cpu")
    fake.add("kube_node_status_capacity", [8.0 * GI] * hours, node="n1", resource="memory")


def prom_of(fake: FakePrometheus) -> Any:
    return lambda t: _prom(fake, t)


def body(amounts: dict[str, float], unit: str = "USD", estimated: bool = False) -> dict[str, Any]:
    return {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": d, "End": d},
                "Total": {"UnblendedCost": {"Amount": str(a), "Unit": unit}},
                "Estimated": estimated,
            }
            for d, a in amounts.items()
        ]
    }


class CostExplorer:
    """Cost Explorer, counting what was asked."""

    def __init__(self, amounts: dict[str, float] | None = None) -> None:
        self.asked: list[httpx.Request] = []
        self.amounts = amounts if amounts is not None else dict.fromkeys(DAYS, 2.2)
        self.status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"__type": "x", "message": SECRET})
        return httpx.Response(200, json=body(self.amounts))

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


@pytest.fixture
async def store(database_url: str) -> Any:
    async with connect(database_url) as pool:
        s = Store(pool)
        await s.migrate()
        yield s


def test_the_period_is_full_utc_days_ending_two_days_ago() -> None:
    assert billing.period(NOW, 7) == DAYS
    assert billing.period(NOW + 86_399, 1) == ["1972-09-25"]  # still the same UTC day
    assert billing.period(NOW + 86_400, 1) == ["1972-09-26"]


def test_the_request_asks_for_the_tags_ec2_compute_usage_before_credits() -> None:
    sent = billing.request(TAG, "1972-09-01", "1972-09-26")
    assert sent["TimePeriod"] == {"Start": "1972-09-01", "End": "1972-09-26"}
    assert sent["Granularity"] == "DAILY" and sent["Metrics"] == ["UnblendedCost"]
    assert sent["Filter"]["And"] == [
        {"Tags": {"Key": "aiops-cluster", "Values": ["kind"], "MatchOptions": ["EQUALS"]}},
        {"Dimensions": {"Key": "SERVICE", "Values": ["Amazon Elastic Compute Cloud - Compute"]}},
        {"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Usage"]}},
    ]
    assert billing.request(TAG, "a", "b", "next")["NextPageToken"] == "next"


def test_a_tag_value_may_hold_an_equals_sign() -> None:
    assert billing.request("k=a=b", "a", "b")["Filter"]["And"][0]["Tags"]["Values"] == ["a=b"]


def test_the_days_are_parsed_with_their_unit_and_whether_aws_may_still_change_them() -> None:
    assert billing.parse(body({"1972-09-25": 2.5}, "EUR", estimated=True)) == {
        "1972-09-25": (2.5, "EUR", True)
    }


def test_the_request_is_signed_and_the_secret_never_sent() -> None:
    ce = CostExplorer()
    got = billing.fetch(
        ce.client(), "AKIAIOSFODNN7EXAMPLE", SECRET, TAG, DAYS[0], "1972-09-26", NOW
    )
    assert got[DAYS[0]] == (2.2, "USD", False)
    (sent,) = ce.asked
    assert sent.url.host == "ce.us-east-1.amazonaws.com"
    assert sent.headers["x-amz-target"] == "AWSInsightsIndexService.GetCostAndUsage"
    assert sent.headers["authorization"].startswith(
        "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/19720927/us-east-1/ce/aws4_request"
    )
    assert SECRET not in str(sent.headers) + sent.content.decode()


def test_every_page_is_read() -> None:
    pages = [
        {**body({DAYS[0]: 1.0}), "NextPageToken": "t2"},
        body({DAYS[1]: 2.0}),
    ]
    tokens = []

    def handler(request: httpx.Request) -> httpx.Response:
        tokens.append(json.loads(request.content).get("NextPageToken"))
        return httpx.Response(200, json=pages[len(tokens) - 1])

    http = httpx.Client(transport=httpx.MockTransport(handler))
    got = billing.fetch(http, "AKIAIOSFODNN7EXAMPLE", SECRET, TAG, DAYS[0], DAYS[2], NOW)
    assert tokens == [None, "t2"] and set(got) == {DAYS[0], DAYS[1]}


def test_the_gap_is_a_fraction_of_the_bill() -> None:
    assert billing.gap(105, 100) == pytest.approx(0.05)
    assert billing.gap(90, 100) == pytest.approx(-0.10)
    assert billing.gap(0, 0) == 0.0
    assert billing.gap(1, 0) is None  # no fraction of nothing


async def seed(
    store: Store, c: contracts.Contract, amounts: dict[str, float], unit: str = "USD"
) -> None:
    await store.save_bill(c.id, "test", {d: (a, unit, False) for d, a in amounts.items()}, NOW)


async def row(
    store: Store, c: contracts.Contract, fake: FakePrometheus, days: int = 7
) -> dict[str, Any]:
    (got,) = await billing.report(store, c, NOW, days, prom_of(fake))
    return got


@pytest.mark.anyio
async def test_a_bill_within_five_percent_reconciles(store: Store) -> None:
    c, fake = billed(), FakePrometheus()
    nodes(fake)
    await seed(store, c, dict.fromkeys(DAYS, 2.2))  # 15.40 billed
    got = await row(store, c, fake)
    assert got["billed"] == pytest.approx(15.4) and got["estimated"] == pytest.approx(ESTIMATE)
    assert got["gap"] == pytest.approx((ESTIMATE - 15.4) / 15.4)  # +0.36%
    assert got["within"] is True and got["note"] is None
    assert (got["start"], got["end"], got["currency"]) == (DAYS[0], DAYS[-1], "USD")


@pytest.mark.anyio
async def test_a_bill_further_away_is_flagged(store: Store) -> None:
    c, fake = billed(), FakePrometheus()
    nodes(fake)
    await seed(store, c, dict.fromkeys(DAYS, 2.0))  # 14.00 billed
    got = await row(store, c, fake)
    assert got["gap"] == pytest.approx((ESTIMATE - 14.0) / 14.0)  # +10.4%
    assert got["within"] is False


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("gap", "within"), [(0.049, True), (0.051, False), (-0.049, True), (-0.051, False)]
)
async def test_five_percent_is_the_edge_either_way(store: Store, gap: float, within: bool) -> None:
    c, fake = billed(), FakePrometheus()
    nodes(fake)
    total = ESTIMATE / (1 + gap)
    await seed(store, c, dict.fromkeys(DAYS, total / 7))
    got = await row(store, c, fake)
    assert got["gap"] == pytest.approx(gap) and got["within"] is within


@pytest.mark.anyio
async def test_a_day_without_a_bill_says_so_and_has_no_gap(store: Store) -> None:
    c, fake = billed(), FakePrometheus()
    nodes(fake)
    await seed(store, c, dict.fromkeys(DAYS[:5], 2.2))  # the 24th and 25th not settled yet
    got = await row(store, c, fake)
    assert got["gap"] is None and got["billed"] is None and got["within"] is None
    assert "no bill for 2 of 7 days yet (first 1972-09-24)" in got["note"]
    assert fake.queries == []  # nothing to compare: Prometheus not asked


@pytest.mark.anyio
async def test_before_the_first_read_the_note_says_the_next_run_reads_it(store: Store) -> None:
    got = await row(store, billed(), FakePrometheus())
    assert "not read yet" in got["note"]


@pytest.mark.anyio
async def test_a_failed_read_is_named_and_the_stored_days_stay(store: Store) -> None:
    c = billed()
    await seed(store, c, dict.fromkeys(DAYS[2:], 2.2))
    await store.fail_bill(c.id, "test", "HTTP 403 from ce.us-east-1.amazonaws.com", NOW)
    got = await row(store, c, FakePrometheus())
    assert got["note"] == "the bill failed to read: HTTP 403 from ce.us-east-1.amazonaws.com"
    days, tries = await store.bills(c.id)
    assert len(days["test"]) == 5 and tries["test"]["ok_at"] == NOW  # the last good read kept


@pytest.mark.anyio
async def test_a_bill_in_another_currency_is_shown_without_a_gap(store: Store) -> None:
    c, fake = billed(), FakePrometheus()
    nodes(fake)
    await seed(store, c, dict.fromkeys(DAYS, 2.2), unit="EUR")
    got = await row(store, c, fake)
    assert got["billed"] == pytest.approx(15.4) and got["currency"] == "EUR"
    assert got["gap"] is None and got["estimated"] is None
    assert "bill is in EUR and the prices in USD: not converted" in got["note"]


@pytest.mark.anyio
async def test_a_cluster_without_a_price_has_no_estimate(store: Store) -> None:
    data = billed().model_dump()
    data["prices"] = None
    c = contracts.build(data, secrets={"aws-key": SecretStr(SECRET)})
    await seed(store, c, dict.fromkeys(DAYS, 2.2))
    got = await row(store, c, FakePrometheus())
    assert got["billed"] == pytest.approx(15.4) and got["estimated"] is None
    assert "no price for this cluster" in got["note"]


@pytest.mark.anyio
async def test_prometheus_down_leaves_the_bill_and_says_why(store: Store) -> None:
    c, fake = billed(), FakePrometheus()
    fake.status = 500
    await seed(store, c, dict.fromkeys(DAYS, 2.2))
    got = await row(store, c, fake)
    assert got["billed"] == pytest.approx(15.4) and got["estimated"] is None
    assert got["note"].startswith("the node-hours failed to read: Prometheus error 500")


@pytest.mark.anyio
async def test_fewer_days_ask_for_fewer_node_hours(store: Store) -> None:
    c, fake = billed(), FakePrometheus()
    nodes(fake, hours=24)
    await seed(store, c, dict.fromkeys(DAYS, 2.2))
    got = await row(store, c, fake, days=1)
    assert got["start"] == got["end"] == DAYS[-1] and got["billed"] == pytest.approx(2.2)
    assert got["estimated"] == pytest.approx(48 * 0.03 + 192 * 0.004)  # 2.208


@pytest.mark.anyio
async def test_the_bill_is_read_daily_and_a_failure_is_tried_again_after_an_hour(
    store: Store,
) -> None:
    c, ce = billed(), CostExplorer()
    http = ce.client()
    assert await billing.refresh(store, [c], http, NOW) == 1
    assert await billing.refresh(store, [c], http, NOW + 23 * H) == 0
    assert await billing.refresh(store, [c], http, NOW + 25 * H) == 1
    assert await billing.refresh(store, [c], http, NOW + 26 * H) == 0  # a re-read counts too
    ce.status = 403
    assert await billing.refresh(store, [c], http, NOW + 50 * H) == 1  # a day on: fails
    assert await billing.refresh(store, [c], http, NOW + 50.5 * H) == 0  # waits an hour
    assert await billing.refresh(store, [c], http, NOW + 51.5 * H) == 1
    days, tries = await store.bills(c.id)
    assert (
        len(days["test"]) == 7
        and tries["test"]["error"] == "HTTP 403 from ce.us-east-1.amazonaws.com"
    )
    assert SECRET not in tries["test"]["error"]


@pytest.mark.anyio
async def test_force_reads_now(store: Store) -> None:
    c, ce = billed(), CostExplorer()
    assert await billing.refresh(store, [c], ce.client(), NOW) == 1
    assert await billing.refresh(store, [c], ce.client(), NOW + H, force=True) == 1


@pytest.mark.anyio
async def test_the_read_covers_the_last_thirty_full_days_and_not_today(store: Store) -> None:
    ce = CostExplorer()
    await billing.refresh(store, [billed()], ce.client(), NOW + 5 * H)
    sent = json.loads(ce.asked[0].content)
    assert sent["TimePeriod"] == {"Start": "1972-08-28", "End": "1972-09-27"}  # 27th is today


@pytest.mark.anyio
async def test_a_cluster_without_billing_is_never_read(store: Store) -> None:
    ce = CostExplorer()
    assert await billing.refresh(store, [make_contract()], ce.client(), NOW) == 0
    assert ce.asked == []


@pytest.mark.anyio
async def test_two_contracts_bills_stay_apart(store: Store) -> None:
    c = billed()
    await seed(store, c, dict.fromkeys(DAYS, 2.2))
    days, tries = await store.bills("other")
    assert days == {} and tries == {}


def test_the_estimate_counts_the_clusters_node_hours() -> None:
    fake = FakePrometheus()
    nodes(fake, hours=48)
    t = usage.Target("test", "http://prometheus", None, {}, ["shop"])
    vcpu, gib = usage.node_hours(_prom(fake, t), t, 0, 48 * 3600 - 1)
    assert (vcpu, gib) == (96.0, 384.0)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"aws": False}, "set billing: it reads the aws integration"),
        ({"prometheus": False}, "set billing: they need a Prometheus"),
    ],
)
def test_billing_needs_the_aws_integration_and_a_prometheus(
    change: dict[str, bool], message: str
) -> None:
    data = billed().model_dump()
    data["integrations"] = [
        i
        for i in data["integrations"]
        if not (i["name"] == "aws" and change.get("aws") is False)
        and not (i["name"] == "prometheus" and change.get("prometheus") is False)
    ]
    with pytest.raises(ValidationError, match=message):
        contracts.build(data)


@pytest.mark.parametrize(
    "tag", ["", "novalue", "=v", "k=", "k=v\nx", "k=" + "v" * 257, "a" * 129 + "=v"]
)
def test_a_malformed_tag_is_refused(tag: str) -> None:
    with pytest.raises(ValidationError, match="billing"):
        billed(billing={"tag": tag})


def test_the_hub_reads_the_bill_with_its_hourly_run(
    settings: Settings, fake_cluster: Any, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.database_url = SecretStr(database_url)
    fake = FakePrometheus()
    nodes(fake)
    monkeypatch.setattr(usage, "Prom", lambda t: _prom(fake, t))
    ce = CostExplorer()
    with client(
        settings,
        fake_cluster,
        more={"bills": (billed("bills"), fake_cluster)},
        bill_http=ce.client(),
    ) as c:
        assert c.portal is not None

        def tick(at: float) -> None:
            c.portal.call(c.app.state.due_sizings, at)  # type: ignore[union-attr,attr-defined]

        tick(NOW)
        assert len(ce.asked) == 1
        tick(NOW + H)
        assert len(ce.asked) == 1  # once a day
        ce.status = 503
        tick(NOW + 25 * H)  # a bill that is down never stops the runs
        assert len(ce.asked) == 2
