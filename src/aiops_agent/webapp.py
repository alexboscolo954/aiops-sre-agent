"""The console app (slice 9.5a): a React single-page app at /app/ and its JSON API at
/api/v1/, beside the Jinja console until Phase 11 rebuilds the rest in it.

The same doors as the Jinja console (console.py): the page and its files need a
listed Operator's Tailscale identity; every API call also needs the approver cookie,
and answers 401 with the token page's address without it. The app is built in the
image's Docker build (console/, Vite) into AIOPS_APP_DIR; nothing loads from a CDN,
and its CSP allows nothing but the Hub's own origin. Since 11.5a it carries
model-written text (Reports, Answers, tool output) and alert titles from client
Alertmanagers, as fields: the app renders everything as text, never as markup, and
an Evidence link as text too, never a link.
"""

import hmac
import json
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from aiops_agent import agenda, billing, listprices, sizing, usage
from aiops_agent.console import COOKIE, action_key, same_origin, scenario_file, set_cookie
from aiops_agent.contracts import Contract
from aiops_agent.models import Answer, CheckResult, Investigation, TriageReport
from aiops_agent.store import Store

log = logging.getLogger("aiops.webapp")

APP_DIR = Path(os.environ.get("AIOPS_APP_DIR", "/opt/aiops/app"))
HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
}
ASSET = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]*")  # Vite's hashed names; no path
TYPES = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}
TOKEN_PAGE = "/app/?view=token"  # noqa: S105 (a page, not a secret)
SHOWN = 4000  # characters of a tool call's result, as the Jinja page shows
DAY = 86400.0


class Risk(BaseModel):
    kind: str
    text: str
    container: str | None = None


class Resource(BaseModel):
    action: str
    current: float | None
    target: float
    basis: float


class Waste(BaseModel):
    cpu: float = 0.0  # cores
    memory: float = 0.0  # bytes


class Cost(BaseModel):
    """Monthly, in the Contract's currency (slice 10.1)."""

    waste: float  # its requests above the Sizings
    requests: float  # every request, ready or not


class Container(BaseModel):
    workload: str
    cluster: str
    namespace: str
    kind: str
    name: str
    container: str
    policy: str
    state: Literal["ready", "learning", "excluded"]
    history_h: float | None = None
    needs_h: float | None = None
    pods: float | None = None
    cpu: Resource | None = None
    memory: Resource | None = None
    waste: Waste | None = None
    risks: list[Risk] = []


class Workload(BaseModel):
    workload: str
    cluster: str
    namespace: str
    kind: str
    name: str
    pods: float
    waste: Waste
    cost: Cost | None = None  # None: the Contract has no prices
    risks: list[Risk]
    containers: list[Container]


class Change(BaseModel):
    requests: Waste
    waste: Waste
    cost: Cost | None = None  # None: the Contract has no prices


class Group(BaseModel):
    group: str  # cluster/namespace, a team or a label value
    workloads: int
    requests: Waste  # cores and bytes, ready or not
    waste: Waste  # priced, the available Savings
    cost: Cost | None = None  # None: the Contract has no prices
    change: Change | None = None  # since the compared run; None: not compared


class Compared(BaseModel):
    at: float | None  # the cluster's run compared with; None: none that old, left out
    oldest: float | None  # its oldest stored run


class Comparison(BaseModel):
    since: float
    clusters: dict[str, Compared]
    change: Change  # the Contract's, of what both sides know
    left_out: list[str]  # containers whose requests or labels were unknown then


class SpentCost(BaseModel):
    rate: float
    accrued: float


class SavingsCost(BaseModel):
    rate: float  # a month's worth, at today's prices
    accrued: float  # since each drop
    week: float  # the rate of the drops of the last 7 days


class Drop(BaseModel):
    workload: str  # cluster/namespace/kind/name/container
    resource: Literal["cpu", "memory"]
    at: float  # the run that saw it
    before: float  # the request per pod
    after: float
    sizing: float
    pods: float  # in the container's latest run
    saved: float  # cores or bytes: (before - after) x pods
    cost: SpentCost | None = None


class Realized(BaseModel):
    currency: str | None = None
    rate: Waste  # cores and bytes held less, now
    accrued: Waste  # core-hours and byte-hours
    week: Waste
    cost: SavingsCost | None = None  # None: the Contract has no prices
    drops: list[Drop]  # by what they save


class Bill(BaseModel):
    """A billed cluster's cloud bill beside its estimate; `note` says why there is none."""

    cluster: str
    tag: str
    start: str
    end: str
    days: int
    billed: float | None
    estimated: float | None
    currency: str | None
    gap: float | None
    within: bool | None  # None with a gap: too few sampled hours to judge
    hours: int  # node-hours a complete estimate rests on
    sampled: int | None
    coverage: float | None
    note: str | None


class Bills(BaseModel):
    tolerance: float
    min_coverage: float
    clusters: list[Bill]


class PriceNote(BaseModel):
    cluster: str
    source: str  # typed, list, or none (the note says why)
    note: str


class Allocation(BaseModel):
    contract: str
    by: str  # namespace, team or label:<key>
    currency: str | None = None
    total: Change
    groups: list[Group]  # ranked by what their requests cost; then any gone since
    compare: Comparison | None = None
    realized: Realized
    groupings: list[str]  # what this Contract can be grouped by
    warnings: list[str]  # clusters where no pod has a label the grouping reads
    prices: list[PriceNote] = []  # where each cluster's price comes from (list_prices)


class ClusterStatus(BaseModel):
    at: float | None  # the latest run that read it
    error: str | None  # why the runs since failed
    since: float | None


class Workloads(BaseModel):
    contract: str
    clusters: dict[str, ClusterStatus]
    total: Waste
    currency: str | None = None  # the Contract's prices', when it has them
    cost: Cost | None = None
    workloads: list[Workload]  # ranked by waste, by its cost when priced
    learning: list[Container]
    excluded: list[Container]
    prices: list[PriceNote] = []


class Point(BaseModel):
    at: float
    pods: float | None = None
    cpu: Resource | None = None
    memory: Resource | None = None


class History(BaseModel):
    points: list[Point]  # oldest first: hourly over 14 days, the last of each day over 400


class ContractSummary(BaseModel):
    id: str
    name: str


class Brief(BaseModel):
    """An Investigation in a list (slice 11.5a)."""

    id: str
    contract: str
    kind: str
    title: str
    status: str
    failed: bool  # a Check whose verdict is no, whatever its Run's status
    started: float


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


class Decision(BaseModel):
    approve: bool
    actions: list[str]  # the Proposed actions' tool names
    message: str
    decided_by: str
    at: float


class Related(BaseModel):
    title: str
    matched: dict[str, str]
    louder: bool
    at: float
    separate_id: str | None


class ToolCall(BaseModel):
    tool: str
    args: dict[str, Any]
    result: str  # its first SHOWN characters
    is_error: bool


class Verdict(BaseModel):
    correct: bool
    correction: str | None
    by: str
    at: float


class Taught(BaseModel):
    id: int
    status: str
    text: str


class InvestigationPage(Brief):
    """One Investigation in full: its Report, Answer or Check verdict as fields (the
    app shows each as text), what waits for a decision, and what it did."""

    error: str | None
    deadline: float | None
    report: TriageReport | None
    answer: Answer | None
    check_result: CheckResult | None
    pending: list[str]  # each Proposed action's description
    executed_actions: list[str]
    usage: Usage
    masked: dict[str, int]
    decisions: list[Decision]
    related: list[Related]
    tool_calls: list[ToolCall]
    feedback: list[Verdict]
    taught: list[Taught]
    scenario: bool  # finished, with its input recorded: it downloads as a Scenario


def brief(t: Investigation) -> dict[str, Any]:
    failed = bool(t.check_result and not t.check_result.passed)
    return {
        "id": t.id,
        "contract": t.contract_id,
        "kind": t.kind,
        "title": t.title,
        "status": t.status,
        "failed": failed,
        "started": t.started,
    }


class Token(BaseModel):
    token: str


class KillSwitch(BaseModel):
    """A Contract's Kill switch (slice 11.2a): who turned it on, and when."""

    on: bool
    by: str | None = None
    since: float | None = None


def daily(points: list[Point]) -> list[Point]:
    """The last point of each UTC day."""
    last: dict[int, Point] = {}
    for p in points:
        last[int(p.at // DAY)] = p
    return list(last.values())


async def workloads_of(st: Store, c: Contract, now: float) -> Workloads:
    """The Contract's latest Sizings, ranked: the Workloads page's and the Hub MCP
    server's (slice 11.1a)."""
    c = await listprices.effective(st, c, now)
    rows, clusters = await st.latest_sizings(c.id, {t.cluster for t in usage.targets(c)})
    return Workloads.model_validate({"contract": c.id, **sizing.report(rows, clusters, c)})


async def allocation_of(
    st: Store, c: Contract, by: str, now: float, compare: int | None
) -> Allocation:
    """Cost by namespace, team or label, compared with `compare` days ago: the Cost
    page's and the Hub MCP server's (slice 11.1b). ValueError: a grouping it can't do."""
    if by not in sizing.groupings(c):
        raise ValueError(f"by is one of {', '.join(sizing.groupings(c))}")
    back = None if compare is None else compare * DAY
    return Allocation.model_validate(await sizing.cost(st, c, by, now, back))


def router(
    operators: set[str],
    by_id: dict[str, Contract],
    store: Callable[[], Store],
    approver_token: str,
    now: Callable[[], float],
) -> APIRouter:
    key = action_key(approver_token)
    r = APIRouter()

    def operator(request: Request) -> str:
        login = request.headers.get("Tailscale-User-Login", "").strip()
        if not login or login not in operators:
            raise HTTPException(403, "not an Operator (sign in through tailscale serve)")
        return login

    def viewer(request: Request, response: Response, login: str = Depends(operator)) -> str:
        response.headers.update(HEADERS)
        if not hmac.compare_digest(request.cookies.get(COOKIE, ""), key):
            raise HTTPException(
                401, {"error": "paste the approver token first", "token_url": TOKEN_PAGE}
            )
        return login

    def changing(request: Request, login: str = Depends(viewer)) -> str:
        """A change, not a read: also from the console's own pages, so another site
        can't make the browser send it (the Jinja console's rule)."""
        if not same_origin(request):
            raise HTTPException(403, "cross-site request refused")
        return login

    def contract(contract_id: str) -> Contract:
        c = by_id.get(contract_id)
        if c is None:
            raise HTTPException(404, "unknown Contract")
        return c

    @r.post("/api/v1/token", status_code=204)
    async def token(given: Token, request: Request) -> Response:
        """The token page's: the identity and the console's own page only, since it is
        what earns the cookie every other call needs."""
        operator(request)
        if not same_origin(request):
            raise HTTPException(403, "cross-site request refused")
        if not hmac.compare_digest(given.token.encode(), approver_token.encode()):
            raise HTTPException(403, "that is not the approver token")
        done = Response(status_code=204, headers=HEADERS)
        set_cookie(done, key)
        return done

    @r.get("/app/", include_in_schema=False)
    async def page(login: str = Depends(operator)) -> HTMLResponse:
        index = APP_DIR / "index.html"
        if not index.is_file():
            raise HTTPException(404, "the console app isn't built into this image")
        return HTMLResponse(index.read_text(), headers={**HEADERS, "Cache-Control": "no-store"})

    @r.get("/app/assets/{name}", include_in_schema=False)
    async def asset(name: str, login: str = Depends(operator)) -> Response:
        path = APP_DIR / "assets" / name
        if not ASSET.fullmatch(name) or not path.is_file():
            raise HTTPException(404, "no such file")
        media = TYPES.get(path.suffix, "application/octet-stream")
        cache = {"Cache-Control": "max-age=31536000, immutable"}  # hashed names
        return Response(path.read_bytes(), media_type=media, headers={**HEADERS, **cache})

    api = APIRouter(prefix="/api/v1", dependencies=[Depends(viewer)])

    @api.get("/contracts")
    async def contracts() -> list[ContractSummary]:
        return [
            ContractSummary(id=c.id, name=c.name)
            for c in sorted(by_id.values(), key=lambda c: c.id)
        ]

    @api.get("/contracts/{contract_id}/workloads")
    async def workloads(contract_id: str) -> Workloads:
        return await workloads_of(store(), contract(contract_id), now())

    @api.get("/contracts/{contract_id}/cost")
    async def cost(
        contract_id: str,
        by: str = "namespace",
        compare: int | None = Query(None, ge=1, le=400, description="days ago"),
    ) -> Allocation:
        try:
            return await allocation_of(store(), contract(contract_id), by, now(), compare)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

    @api.get("/contracts/{contract_id}/billing")
    async def bills(contract_id: str, days: int = Query(7, ge=1, le=billing.KEPT_DAYS)) -> Bills:
        rows = await billing.report(store(), contract(contract_id), now(), days)
        return Bills.model_validate(
            {"tolerance": billing.TOLERANCE, "min_coverage": billing.MIN_COVERAGE, "clusters": rows}
        )

    @api.get("/contracts/{contract_id}/history")
    async def history(
        contract_id: str,
        cluster: str,
        namespace: str,
        kind: str,
        name: str,
        container: str,
        days: int = Query(14, description="14 (hourly) or 400 (daily)"),
    ) -> History:
        if days not in (14, 400):
            raise HTTPException(422, "days is 14 or 400")
        c = contract(contract_id)
        workload = (cluster, namespace, kind, name, container)
        rows = await store().sizing_history(c.id, workload, now() - days * DAY)
        points = [Point.model_validate({"at": at, **row}) for at, row in rows]
        return History(points=daily(points) if days > 14 else points)

    @api.get("/contracts/{contract_id}/agenda")
    async def now_(contract_id: str) -> agenda.Agenda:
        """What to look at now in this Contract, most urgent first (slice 11.4)."""
        return await agenda.of(store(), contract(contract_id), now())

    @api.get("/contracts/{contract_id}/investigations")
    async def investigations(
        contract_id: str, limit: int = Query(100, ge=1, le=500)
    ) -> list[Brief]:
        """Newest first; passing Checks left out, as the Checks list has their last Run."""
        c = contract(contract_id)
        return [Brief.model_validate(brief(t)) for t in await store().recent(limit, c.id)]

    async def investigation_of(investigation_id: str) -> Investigation:
        t = await store().get(investigation_id)
        if t is None or t.contract_id not in by_id:
            raise HTTPException(404, "unknown investigation")
        return t

    @api.get("/investigations/{investigation_id}")
    async def investigation(investigation_id: str) -> InvestigationPage:
        t = await investigation_of(investigation_id)
        st = store()
        return InvestigationPage.model_validate(
            {
                **brief(t),
                "error": t.error,
                "deadline": t.deadline,
                "report": t.report,
                "answer": t.answer,
                "check_result": t.check_result,
                "pending": [str(p.get("description", p.get("name", ""))) for p in t.pending],
                "executed_actions": t.executed_actions,
                "usage": await st.investigation_usage(t.id),
                "masked": await st.masked_counts(t.id),
                "decisions": [
                    {**d, "actions": [a.get("name", "") for a in d["actions"]]}
                    for d in await st.decisions(t.id)
                ],
                "related": await st.related(t.id),
                "tool_calls": [
                    {**c, "result": (c["result"] or "")[:SHOWN]} for c in await st.tool_calls(t.id)
                ],
                "feedback": await st.feedback(t.id),
                "taught": [x for x in await st.teachings(t.contract_id) if x["source_id"] == t.id],
                "scenario": t.status == "done" and t.input is not None,
            }
        )

    @api.get("/investigations/{investigation_id}/scenario.yaml", response_class=Response)
    async def scenario(investigation_id: str) -> Response:
        return await scenario_file(await investigation_of(investigation_id), by_id, store())

    async def switch(c: Contract) -> KillSwitch:
        on = await store().kill_switch(c.id)
        return (
            KillSwitch(on=False)
            if on is None
            else KillSwitch(on=True, by=on["set_by"], since=on["set_at"])
        )

    @api.get("/contracts/{contract_id}/kill-switch")
    async def kill_switch(contract_id: str) -> KillSwitch:
        return await switch(contract(contract_id))

    @api.post("/contracts/{contract_id}/kill-switch")
    async def turn_on(contract_id: str, login: str = Depends(changing)) -> KillSwitch:
        c = contract(contract_id)
        if await store().turn_on_kill_switch(c.id, f"console:{login}", now()):
            log.info("kill switch %s on by console:%s", c.id, login)
        return await switch(c)

    @api.delete("/contracts/{contract_id}/kill-switch")
    async def turn_off(contract_id: str, login: str = Depends(changing)) -> KillSwitch:
        """The only way a Kill switch goes off: the Operator, in the console."""
        c = contract(contract_id)
        if await store().turn_off_kill_switch(c.id):
            log.info("kill switch %s off by console:%s", c.id, login)
        return await switch(c)

    r.include_router(api)
    return r


def openapi() -> str:
    """The API's schema, as console/openapi.json holds it (the app's types come from
    it: `make console-types`)."""
    app = FastAPI(title="aiops console", version="1")
    app.include_router(router(set(), {}, lambda: None, "x", lambda: 0.0))  # type: ignore[arg-type,return-value]
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
