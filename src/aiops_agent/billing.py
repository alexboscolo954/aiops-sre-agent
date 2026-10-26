"""AWS bills (slice 10.5a): what Cost Explorer says a cluster's tagged EC2 compute cost,
set beside what its node-hours cost at the Hub's prices. Read-only; a shown cost never
changes (a billed rate feeding prices is a later slice)."""

import asyncio
import json
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx

from aiops_agent import listprices, usage
from aiops_agent.contracts import Aws, Contract
from aiops_agent.servers.aws import authorization

if TYPE_CHECKING:
    from aiops_agent.store import Store

TOLERANCE = 0.05  # the estimate may differ from the bill by this much and still reconcile
LAG_DAYS = 2  # Cost Explorer settles a day within about 24 to 48 hours
KEPT_DAYS = 30  # days read each time, and the most `--days` takes
DAY = 86400
HOUR = 3600
HOST = "ce.us-east-1.amazonaws.com"  # Cost Explorer has this one endpoint
COMPUTE = "Amazon Elastic Compute Cloud - Compute"
Bill = dict[str, tuple[float, str, bool]]  # day -> amount, currency, still estimated


def utc_day(at: float) -> date:
    return datetime.fromtimestamp(at, UTC).date()


def period(now: float, days: int) -> list[str]:
    """The `days` full UTC days ending LAG_DAYS days ago, oldest first."""
    last = utc_day(now) - timedelta(days=LAG_DAYS)
    return [(last - timedelta(days=i)).isoformat() for i in reversed(range(days))]


def request(tag: str, start: str, end: str, token: str | None = None) -> dict[str, Any]:
    """Cost Explorer's GetCostAndUsage body: the tag's EC2 compute, usage only (before
    credits), unblended, a day at a time; `end` is exclusive."""
    key, _, value = tag.partition("=")
    body: dict[str, Any] = {
        "TimePeriod": {"Start": start, "End": end},
        "Granularity": "DAILY",
        "Metrics": ["UnblendedCost"],
        "Filter": {
            "And": [
                {"Tags": {"Key": key, "Values": [value], "MatchOptions": ["EQUALS"]}},
                {"Dimensions": {"Key": "SERVICE", "Values": [COMPUTE]}},
                {"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Usage"]}},
            ]
        },
    }
    if token:
        body["NextPageToken"] = token
    return body


def parse(body: dict[str, Any]) -> Bill:
    out: Bill = {}
    for r in body.get("ResultsByTime", []):
        cost = r["Total"]["UnblendedCost"]
        out[r["TimePeriod"]["Start"]] = (float(cost["Amount"]), cost["Unit"], bool(r["Estimated"]))
    return out


def fetch(
    http: httpx.Client, key_id: str, secret: str, tag: str, start: str, end: str, now: float
) -> Bill:
    """The tag's billed days from `start` up to (not including) `end`."""
    out: Bill = {}
    token = None
    while True:
        data = json.dumps(request(tag, start, end, token)).encode()
        headers = {
            "content-type": "application/x-amz-json-1.1",
            "host": HOST,
            "x-amz-date": datetime.fromtimestamp(now, UTC).strftime("%Y%m%dT%H%M%SZ"),
            "x-amz-target": "AWSInsightsIndexService.GetCostAndUsage",
        }
        auth = authorization(
            "POST", HOST, "/", "", headers, data, "us-east-1", "ce",
            key_id, secret, headers["x-amz-date"],
        )  # fmt: skip
        resp = http.post(
            f"https://{HOST}/", content=data, headers={**headers, "authorization": auth}
        )
        resp.raise_for_status()
        body = resp.json()
        out |= parse(body)
        token = body.get("NextPageToken")
        if not token:
            return out


def client() -> httpx.Client:
    return httpx.Client(timeout=30)


def _aws(c: Contract) -> Aws:
    return next(i for i in c.integrations if isinstance(i, Aws))


async def refresh(
    store: "Store",
    contracts: Iterable[Contract],
    http: httpx.Client,
    now: float,
    force: bool = False,
) -> int:
    """Read every billed cluster's last KEPT_DAYS days unless it was read in the last
    day (a failed read is tried again after an hour); the reads made. A failure keeps
    the days already stored."""
    reads = 0
    end = utc_day(now)  # today is still filling: left out
    start = (end - timedelta(days=KEPT_DAYS)).isoformat()
    for c in contracts:
        billed = [cl for cl in c.clusters if cl.billing]
        if not billed:
            continue
        aws = _aws(c)
        _, tries = await store.bills(c.id)
        for cl in billed:
            assert cl.billing is not None
            row = tries.get(cl.name)
            fresh = row and row["ok_at"] is not None and now - row["ok_at"] < DAY
            waiting = row and row["error"] and now - row["tried_at"] < HOUR
            if not force and (fresh or waiting):
                continue
            reads += 1
            try:
                got = await asyncio.to_thread(
                    fetch,
                    http,
                    aws.access_key_id,
                    c.secret(aws.secret_access_key_secret).get_secret_value(),
                    cl.billing.tag,
                    start,
                    end.isoformat(),
                    now,
                )
            except (httpx.HTTPError, ValueError, KeyError) as e:
                await store.fail_bill(c.id, cl.name, listprices.why(e, None), now)
            else:
                await store.save_bill(c.id, cl.name, got, now)
    return reads


def gap(estimated: float, billed: float) -> float | None:
    """How far the estimate is from the bill, as a fraction of the bill; None when the
    bill is nothing and the estimate isn't (no fraction to speak of)."""
    if billed == 0:
        return 0.0 if estimated == 0 else None
    return (estimated - billed) / billed


async def report(
    store: "Store",
    c: Contract,
    now: float,
    days: int = 7,
    prom: Callable[[usage.Target], usage.Prom] = usage.Prom,
) -> list[dict[str, Any]]:
    """Per billed cluster: the period, the bill, the estimate at the Hub's prices, their
    gap and whether it is within TOLERANCE, or `note` saying why there is none. Money
    stays in the currency it was read in; nothing is converted."""
    wanted = period(now, days)
    c = await listprices.effective(store, c, now)
    have, tries = await store.bills(c.id)
    targets = {t.cluster: t for t in usage.targets(c)}
    out = []
    for cl in c.clusters:
        if not cl.billing:
            continue
        row: dict[str, Any] = {
            "cluster": cl.name,
            "tag": cl.billing.tag,
            "start": wanted[0],
            "end": wanted[-1],
            "days": days,
            "billed": None,
            "estimated": None,
            "currency": None,
            "gap": None,
            "within": None,
            "note": None,
        }
        out.append(row)
        seen = have.get(cl.name, {})
        missing = [d for d in wanted if d not in seen]
        if missing:
            tried = tries.get(cl.name)
            row["note"] = (
                f"the bill failed to read: {tried['error']}"
                if tried and tried["error"]
                else f"no bill for {len(missing)} of {days} days yet "
                f"(first {missing[0]}): read daily, and AWS settles a day in 1 to 2"
                if tried
                else "the bill is not read yet: the next hourly run reads it"
            )
            continue
        currencies = {seen[d]["currency"] for d in wanted}
        row["billed"] = sum(seen[d]["amount"] for d in wanted)
        row["currency"] = currencies.pop() if len(currencies) == 1 else None
        price = c.price(cl.name)
        if price is None:
            row["note"] = "no price for this cluster: its estimate waits for prices or list_prices"
            continue
        money = c.prices.currency if c.prices else "USD"
        if row["currency"] != money:
            row["note"] = (
                f"the bill is in {row['currency']} and the prices in {money}: not converted"
            )
            continue
        t = targets[cl.name]
        first = datetime.fromisoformat(wanted[0]).replace(tzinfo=UTC).timestamp()
        last = datetime.fromisoformat(wanted[-1]).replace(tzinfo=UTC).timestamp() + DAY - 1
        try:
            vcpu, gib = await asyncio.to_thread(usage.node_hours, prom(t), t, first, last)
        except usage.UsageError as e:
            row["note"] = f"the node-hours failed to read: {e}"
            continue
        row["estimated"] = vcpu * price.cpu + gib * price.memory
        row["gap"] = gap(row["estimated"], row["billed"])
        row["within"] = row["gap"] is not None and abs(row["gap"]) <= TOLERANCE
    return out
