"""The console app (slice 9.5a): a React single-page app at /app/ and its JSON API at
/api/v1/, beside the Jinja console until Phase 11 rebuilds the rest in it.

The same doors as the Jinja console (console.py): the page and its files need a
listed Operator's Tailscale identity; every API call also needs the approver cookie,
and answers 401 with the token page's address without it. The app is built in the
image's Docker build (console/, Vite) into AIOPS_APP_DIR; nothing loads from a CDN,
and its CSP allows nothing but the Hub's own origin. Model-written text never reaches
this API yet; Sizings and risks are the Hub's own words, but pod label values come
from client clusters: everything is rendered as text.
"""

import hmac
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from aiops_agent import sizing, usage
from aiops_agent.console import COOKIE, action_key
from aiops_agent.contracts import Contract
from aiops_agent.store import Store

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
TOKEN_PAGE = "/console/token"  # noqa: S105 (a page, not a secret)
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


def daily(points: list[Point]) -> list[Point]:
    """The last point of each UTC day."""
    last: dict[int, Point] = {}
    for p in points:
        last[int(p.at // DAY)] = p
    return list(last.values())


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

    def contract(contract_id: str) -> Contract:
        c = by_id.get(contract_id)
        if c is None:
            raise HTTPException(404, "unknown Contract")
        return c

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
        c = contract(contract_id)
        rows, clusters = await store().latest_sizings(c.id, {t.cluster for t in usage.targets(c)})
        return Workloads.model_validate({"contract": c.id, **sizing.report(rows, clusters, c)})

    @api.get("/contracts/{contract_id}/cost")
    async def cost(
        contract_id: str,
        by: str = "namespace",
        compare: int | None = Query(None, ge=1, le=400, description="days ago"),
    ) -> Allocation:
        c = contract(contract_id)
        if by not in sizing.groupings(c):
            raise HTTPException(422, f"by is one of {', '.join(sizing.groupings(c))}")
        back = None if compare is None else compare * DAY
        return Allocation.model_validate(await sizing.cost(store(), c, by, now(), back))

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

    r.include_router(api)
    return r


def openapi() -> str:
    """The API's schema, as console/openapi.json holds it (the app's types come from
    it: `make console-types`)."""
    app = FastAPI(title="aiops console", version="1")
    app.include_router(router(set(), {}, lambda: None, "x", lambda: 0.0))  # type: ignore[arg-type,return-value]
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
