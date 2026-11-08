"""The Agenda (slice 11.4): what the Operator should look at now in one Contract, from
what the Hub already stores, ranked without a model in a fixed order of urgency: the
Kill switch while it is on, pauses waiting for an Approval decision (they go Stale),
failing Checks, data the Hub can't read, Bills outside their tolerance, running
Investigations, and the Workloads whose waste costs most. The Hub MCP server's `now`
and the console app's Workloads page show it.
"""

from collections import Counter
from math import inf
from typing import Literal

from pydantic import BaseModel

from aiops_agent import billing, usage
from aiops_agent.contracts import Contract
from aiops_agent.sizing import show
from aiops_agent.store import Store

Kind = Literal["kill_switch", "approval", "check", "stale", "bill", "investigation", "waste"]
WASTE_TOP = 3


class Item(BaseModel):
    kind: Kind
    title: str
    at: float | None = None  # a pause's deadline; when it started failing, ran or went on
    id: str | None = None  # the Investigation to open
    cluster: str | None = None
    workload: str | None = None  # cluster/namespace/kind/name


class Agenda(BaseModel):
    contract: str
    items: list[Item]


async def of(st: Store, c: Contract, now: float) -> Agenda:
    from aiops_agent import webapp  # webapp serves this: imported here, not in a cycle

    items: list[Item] = []
    if on := await st.kill_switch(c.id):
        items.append(
            Item(
                kind="kill_switch",
                title=f"The Kill switch is on ({on['set_by']}): approving is refused",
                at=on["set_at"],
            )
        )
    mine = [t for t in await st.unfinished() if t.contract_id == c.id]
    paused = [t for t in mine if t.status == "awaiting_approval"]
    for t in sorted(paused, key=lambda t: t.deadline or inf):
        n = len(t.pending)
        items.append(
            Item(
                kind="approval",
                title=f"{n} Proposed action{'s' * (n != 1)} wait{'s' * (n == 1)} for a "
                f"decision: {t.title}",
                at=t.deadline,
                id=t.id,
            )
        )
    # failing as the Hub's Slack thread counts it: a verdict of no, or a Run that errored
    failing = [
        s
        for s in await st.check_schedules(c.id)
        if s["last_passed"] is False or s["last_status"] == "failed"
    ]
    for s in sorted(failing, key=lambda s: -(s["last_started"] or 0)):
        what = "failed" if s["last_passed"] is False else "could not run"
        items.append(
            Item(
                kind="check",
                title=f"Check {s['name']} {what}",
                at=s["last_started"],
                id=s["last_id"],
            )
        )
    w = await webapp.workloads_of(st, c, now)
    stale = [
        Item(kind="stale", title=f"Sizing reads failing: {s.error}", at=s.since, cluster=k)
        for k, s in w.clusters.items()
        if s.error
    ]
    names = {t.cluster for t in usage.targets(c)}
    _, tries = await st.bills(c.id)
    stale += [
        Item(kind="stale", title=f"Bill reads failing: {t['error']}", at=t["tried_at"], cluster=k)
        for k, t in tries.items()
        if t["error"] and k in names
    ]
    items += sorted(stale, key=lambda i: i.at or inf)
    bills = await billing.report(st, c, now, 7)
    outside = [b for b in bills if b["within"] is False]
    for b in sorted(outside, key=lambda b: -abs(b["gap"])):
        items.append(
            Item(
                kind="bill",
                title=f"Bill {b['gap']:+.1%} from the estimate ({b['start']} to {b['end']}), "
                f"outside {billing.TOLERANCE:.0%}",
                cluster=b["cluster"],
            )
        )
    for t in (t for t in mine if t.status == "running"):  # oldest first, as stored
        items.append(Item(kind="investigation", title=f"Running: {t.title}", at=t.started, id=t.id))
    wasting = [x for x in w.workloads if x.waste.cpu or x.waste.memory][:WASTE_TOP]
    for x in wasting:
        size = f"{show('cpu', x.waste.cpu)} and {show('memory', x.waste.memory)}"
        money = f"{x.cost.waste:.2f} {w.currency} a month, " if x.cost and w.currency else ""
        items.append(
            Item(
                kind="waste",
                title=f"Waste: {money}{size} above its Sizings",
                cluster=x.cluster,
                workload=x.workload,
            )
        )
    return Agenda(contract=c.id, items=items)


def counts(a: Agenda) -> dict[str, int]:
    return dict(Counter(i.kind for i in a.items))
