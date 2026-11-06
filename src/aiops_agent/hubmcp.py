"""The Hub MCP server (slice 11.1a): the Operator's own MCP endpoint at /mcp/, for an MCP
client such as Claude Code on the Operator's devices.

Two doors, both required: the bearer AIOPS_MCP_TOKEN, and a listed Operator's Tailscale
identity, which `tailscale serve` adds to what it proxies (and strips from what a client
sends). The token alone could come from anything that read the Hub's env; the identity
header alone from anything else that reaches the port. Stateless HTTP: a Hub restart
(every contracts update) leaves no session for a client to lose.

Every tool takes one Contract and answers within it. What it returns reaches the
client's model, so it follows that Contract's Data policy as the Hub's own agent does:
secrets redacted, identifiers masked with the Contract's own key, error text included.
A placeholder in an argument becomes its value again only when this server handed it
out for that same Contract, the `contract` argument included (a client's id is likely
one of its own terms).

The Investigation agent never gets these tools: they live here, not in servers/.
"""

import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import MiddlewareContext
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from aiops_agent import billing, masking, usage, webapp
from aiops_agent.console import QUESTION_LIMIT
from aiops_agent.contracts import Contract
from aiops_agent.models import Investigation
from aiops_agent.observability import AuditMiddleware
from aiops_agent.servers.sizing import workload
from aiops_agent.sizing import show
from aiops_agent.store import Store

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
# a Question changes nothing in a cluster, but it starts a run that costs model money
ASK = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True)
CONTRACT = Field(description="The Contract's id, as list_contracts gives it")
LOGIN = "tailscale-user-login"


def guard(app: ASGIApp, token: str, operators: set[str]) -> ASGIApp:
    """The MCP app behind both doors; lifespan events pass through."""
    expected = f"Bearer {token}".encode()

    async def asgi(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = Headers(scope=scope)
            if not secrets.compare_digest(headers.get("authorization", "").encode(), expected):
                await JSONResponse({"error": "invalid token"}, 401)(scope, receive, send)
                return
            if headers.get(LOGIN, "").strip() not in operators:
                error = "not an Operator (connect through tailscale serve)"
                await JSONResponse({"error": error}, 403)(scope, receive, send)
                return
        await app(scope, receive, send)

    return asgi


class Audit(AuditMiddleware):
    """The agent's audit line, saying it came through the Hub MCP server, from whom,
    about which Contract (as the client wrote it: masked arguments stay masked)."""

    def who(self, context: MiddlewareContext[Any]) -> dict[str, Any]:
        login = get_http_headers().get(LOGIN, "").strip() or None
        contract = (context.message.arguments or {}).get("contract")
        return {"channel": "mcp", "login": login, "contract": contract}


def _date(epoch: float | None) -> str | None:
    return (
        None if epoch is None else datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%d %H:%M UTC")
    )


def _resource(res: str, r: webapp.Resource | None) -> dict[str, Any] | None:
    if r is None:
        return None
    now = None if r.current is None else show(res, r.current)
    return {"request": now, "sizing": show(res, r.target), "action": r.action}


def _workload(w: webapp.Workload) -> dict[str, Any]:
    """A ranked Workload as the client's model reads it: quantities as 115m and 96Mi."""
    return {
        "workload": w.workload,
        "pods": w.pods,
        "waste": {"cpu": show("cpu", w.waste.cpu), "memory": show("memory", w.waste.memory)},
        "cost": None if w.cost is None else w.cost.model_dump(),
        "risks": [r.text for r in w.risks],
        "containers": [
            {
                "container": c.container,
                "cpu": _resource("cpu", c.cpu),
                "memory": _resource("memory", c.memory),
            }
            for c in w.containers
        ],
    }


def build(
    by_id: dict[str, Contract],
    store: Callable[[], Store],
    now: Callable[[], float],
    asked: Callable[[str, str], Awaitable[str | None]],
) -> FastMCP:
    """asked(contract id, text): a new Question's id, as the console asks it."""
    maskers = {cid: masking.for_contract(c) for cid, c in by_id.items()}
    # ponytail: in memory, so a restart forgets what was handed out (the client lists
    # again); grows with the distinct identifiers shown, which a Contract bounds
    seen: dict[str, masking.Seen] = {cid: {} for cid in by_id}
    mcp = FastMCP(
        "aiops-hub",
        instructions="The Hub's stored view of each Contract. Every tool takes one Contract: "
        "list_contracts names them.",
        mask_error_details=True,  # an unexpected error's text could carry client data
    )
    mcp.add_middleware(Audit(None))

    def out(c: Contract, value: Any) -> Any:
        return masking._walk(value, lambda s: masking.outgoing(maskers[c.id], s, seen[c.id]))

    def arg(c: Contract, value: str) -> str:
        return masking.unmask(value, seen[c.id])

    def resolve(value: str) -> Contract:
        for c in by_id.values():
            if arg(c, value) == c.id:
                return c
        raise ToolError("unknown Contract: list_contracts names them")

    async def answer(c: Contract, work: Awaitable[Any]) -> Any:
        try:
            return out(c, await work)
        except ToolError as e:
            raise ToolError(out(c, str(e))) from None

    @mcp.tool(annotations=READ)
    async def list_contracts() -> list[dict[str, Any]]:
        """Every Contract the Hub serves: its id (pass it as `contract` to the other
        tools), name and clusters."""
        return [
            out(c, {"id": c.id, "name": c.name, "clusters": [t.cluster for t in usage.targets(c)]})
            for c in sorted(by_id.values(), key=lambda c: c.id)
        ]

    @mcp.tool(annotations=READ)
    async def sizings(
        contract: Annotated[str, CONTRACT],
        top: Annotated[int, Field(ge=1, le=100)] = 10,
        cluster: str | None = None,
        namespace: str | None = None,
        risky: bool = False,
    ) -> dict[str, Any]:
        """The Contract's Workloads ranked by what their waste costs (by the waste
        itself when the Contract has no prices), from the Hub's latest Sizing run: each
        one's requests now and its Sizing per container, its waste and risks. risky:
        only Workloads with a risk (an OOM kill, throttling, restarts)."""
        c = resolve(contract)

        async def work() -> dict[str, Any]:
            names = [t.cluster for t in usage.targets(c)]
            wanted = None if cluster is None else arg(c, cluster)
            if wanted is not None and wanted not in names:
                raise ToolError(f"cluster {wanted!r} has no Sizings: one of {names}")
            space = None if namespace is None else arg(c, namespace)
            w = await webapp.workloads_of(store(), c, now())
            found = [
                x
                for x in w.workloads
                if wanted in (None, x.cluster)
                and space in (None, x.namespace)
                and (x.risks or not risky)
            ]
            return {
                "currency": w.currency,
                # a list, not a dict: masking leaves keys alone, and a cluster's name
                # can be the client's
                "clusters": [
                    {
                        "cluster": k,
                        "as_of": _date(s.at),
                        "failing": s.error,
                        "since": _date(s.since),
                    }
                    for k, s in w.clusters.items()
                ],
                "matching": len(found),
                "workloads": [_workload(x) for x in found[:top]],
                "learning": len(w.learning),
                "excluded": len(w.excluded),
            }

        result: dict[str, Any] = await answer(c, work())
        return result

    @mcp.tool(annotations=READ)
    async def sizing(
        contract: Annotated[str, CONTRACT],
        cluster: str,
        namespace: str,
        name: str,
        kind: str | None = None,
    ) -> dict[str, Any]:
        """One Workload's Sizing, per container: requests and limits now, what they
        should be (CPU from its weighted p95, memory from its peak, with headroom), its
        risks and waste. name: the Workload or one of its pods. kind (Deployment,
        StatefulSet, ...) only when two Workloads share a name."""
        c = resolve(contract)
        where = arg(c, cluster), arg(c, namespace), arg(c, name)
        result: dict[str, Any] = await answer(c, workload(store(), c, *where, kind))
        return result

    async def allocation(c: Contract, by: str, compare: int | None) -> webapp.Allocation:
        try:
            return await webapp.allocation_of(store(), c, by, now(), compare)
        except ValueError as e:
            raise ToolError(str(e)) from None

    @mcp.tool(annotations=READ)
    async def cost(
        contract: Annotated[str, CONTRACT],
        by: str = "namespace",
        compare_days: Annotated[int | None, Field(ge=1, le=400)] = None,
    ) -> dict[str, Any]:
        """What the Contract's Workloads cost a month, by namespace, team or
        label:<key> (`groupings` lists what this Contract allows): each group's requests
        and the waste in them (the available Savings), ranked by what the requests cost,
        with each group's change since `compare_days` ago when given. cpu in cores,
        memory in bytes, money a month in `currency`."""
        c = resolve(contract)

        async def work() -> dict[str, Any]:
            a = await allocation(c, arg(c, by), compare_days)
            shown = a.model_dump(mode="json", exclude={"realized", "compare"})
            return {**shown, "compare": _compared(a.compare)}

        result: dict[str, Any] = await answer(c, work())
        return result

    @mcp.tool(annotations=READ)
    async def savings(
        contract: Annotated[str, CONTRACT],
        compare_days: Annotated[int | None, Field(ge=1, le=400)] = None,
    ) -> dict[str, Any]:
        """The Contract's Savings: available (the waste in its requests, a month) and
        realized (requests lowered since: held less now, accrued since each drop, and
        the last 7 days' drops, by what they save), and the change since `compare_days`
        ago when given. cpu in cores, memory in bytes, money in `currency`."""
        c = resolve(contract)

        async def work() -> dict[str, Any]:
            a = await allocation(c, "namespace", compare_days)
            return {
                "currency": a.currency,
                "available": a.total.model_dump(mode="json"),
                "realized": a.realized.model_dump(mode="json"),
                "compare": _compared(a.compare),
                "prices": [p.model_dump(mode="json") for p in a.prices],
            }

        result: dict[str, Any] = await answer(c, work())
        return result

    @mcp.tool(annotations=READ)
    async def bill(
        contract: Annotated[str, CONTRACT],
        days: Annotated[int, Field(ge=1, le=billing.KEPT_DAYS)] = 7,
    ) -> dict[str, Any]:
        """Each billed cluster's cloud bill beside the Hub's estimate over the last full
        days the cloud has settled: billed, estimated, the gap and whether it is within
        the tolerance, and how many node-hours the estimate rests on."""
        c = resolve(contract)

        async def work() -> dict[str, Any]:
            rows = await billing.report(store(), c, now(), days)
            return webapp.Bills.model_validate(
                {
                    "tolerance": billing.TOLERANCE,
                    "min_coverage": billing.MIN_COVERAGE,
                    "clusters": rows,
                }
            ).model_dump(mode="json")

        result: dict[str, Any] = await answer(c, work())
        return result

    @mcp.tool(annotations=READ)
    async def investigations(
        contract: Annotated[str, CONTRACT],
        open: bool = False,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> list[dict[str, Any]]:
        """The Contract's Investigations, newest first (Triages, Questions and failing
        Checks): each one's status, and its Category, severity and summary, Answer or
        verdict. open: only those still running or waiting for an Approval decision."""
        c = resolve(contract)

        async def work() -> list[dict[str, Any]]:
            if open:
                found = [t for t in await store().unfinished() if t.contract_id == c.id]
                found.reverse()  # newest first, like recent()
            else:
                found = await store().recent(limit, c.id)
            return [_brief(t, lambda s: out(c, s)) for t in found[:limit]]

        result: list[dict[str, Any]] = await answer(c, work())
        return result

    @mcp.tool(annotations=READ)
    async def investigation(contract: Annotated[str, CONTRACT], id: str) -> dict[str, Any]:
        """One Investigation of this Contract in full: its Report, Answer or Check
        verdict with their Evidence, the Proposed actions waiting for a decision, the
        Approval decisions made and the actions executed."""
        c = resolve(contract)

        async def work() -> dict[str, Any]:
            t = await store().get(id)
            if t is None or t.contract_id != c.id:  # another Contract's is never shown
                raise ToolError("no such Investigation in this Contract")
            full = _brief(t, lambda s: out(c, s))
            full.update(
                t.model_dump(
                    mode="json",
                    include={"report", "answer", "check_result", "pending", "executed_actions"},
                )
            )
            full["deadline"] = _date(t.deadline)
            full["decisions"] = [{**d, "at": _date(d["at"])} for d in await store().decisions(t.id)]
            return full

        result: dict[str, Any] = await answer(c, work())
        return result

    @mcp.tool(annotations=READ)
    async def checks(contract: Annotated[str, CONTRACT]) -> list[dict[str, Any]]:
        """The Contract's scheduled Checks: each one's schedule, when it runs next, and
        its last Run (status, passed or not, and its id for `investigation`)."""
        c = resolve(contract)

        async def work() -> list[dict[str, Any]]:
            return [
                {
                    "name": s["name"],
                    "schedule": s["schedule"],
                    "next": _date(s["next_due"]),
                    "last": s["last_id"],
                    "last_status": s["last_status"],
                    "last_passed": s["last_passed"],
                    "last_started": _date(s["last_started"]),
                    "skipped": _date(s["skipped_at"]),
                    "skipped_why": s["skipped_reason"],
                }
                for s in await store().check_schedules(c.id)
            ]

        result: list[dict[str, Any]] = await answer(c, work())
        return result

    @mcp.tool(annotations=ASK)
    async def ask(
        contract: Annotated[str, CONTRACT],
        question: Annotated[str, Field(min_length=1, max_length=QUESTION_LIMIT)],
    ) -> dict[str, Any]:
        """Ask the Hub's agent a Question about this Contract. It answers with Evidence
        from the Contract's read tools, in the background (a minute or more, and it costs
        model money): this returns the Question's id at once; read its Answer with
        `investigation`. Stored like a console Question; never posted to Slack."""
        c = resolve(contract)

        async def work() -> dict[str, Any]:
            qid = await asked(c.id, arg(c, question).strip())
            if qid is None:
                raise ToolError("the Question could not be started")
            return {"id": qid, "status": "running"}

        result: dict[str, Any] = await answer(c, work())
        return result

    return mcp


def _compared(compare: webapp.Comparison | None) -> dict[str, Any] | None:
    """The comparison with its clusters in a list: masking leaves keys alone, and a
    cluster's name can be the client's."""
    if compare is None:
        return None
    shown = compare.model_dump(mode="json")
    shown["clusters"] = [{"cluster": k, **v} for k, v in shown["clusters"].items()]
    return shown


def _brief(t: Investigation, mask: Callable[[str], str]) -> dict[str, Any]:
    """An Investigation as a list shows it. Its Answer is cut after `mask`: a term cut
    in two would match nothing (stored titles are cut at 200 before any of this)."""
    out: dict[str, Any] = {
        "id": t.id,
        "kind": t.kind,
        "title": t.title,
        "status": t.status,
        "started": _date(t.started),
    }
    if t.report:
        out.update(t.report.model_dump(mode="json", include={"category", "severity", "summary"}))
    if t.answer:
        out["answer"] = mask(t.answer.answer)[:500]
    if t.check_result:
        out.update(t.check_result.model_dump(mode="json", include={"passed", "summary"}))
    if t.pending:
        out["pending_actions"] = len(t.pending)
    if t.error:
        out["error"] = t.error
    return out
