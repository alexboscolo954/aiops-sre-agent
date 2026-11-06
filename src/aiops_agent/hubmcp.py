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

from aiops_agent import masking, usage, webapp
from aiops_agent.contracts import Contract
from aiops_agent.observability import AuditMiddleware
from aiops_agent.servers.sizing import workload
from aiops_agent.sizing import show
from aiops_agent.store import Store

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
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
    by_id: dict[str, Contract], store: Callable[[], Store], now: Callable[[], float]
) -> FastMCP:
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

    return mcp
