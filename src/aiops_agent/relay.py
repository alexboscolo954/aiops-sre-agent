"""The Relay's connection (slice 3.1): MCP over a websocket the Relay dials, reversed.

A Relay runs inside a client's network and dials the Hub; over that one socket the
Relay is the MCP *server* (its cluster's tools) and the Hub the MCP *client*. mcp 2.3
has no websocket transport, so `bridge` turns any socket into the (read, write) stream
pair MCP runs over, framing each JSON-RPC message as one text frame exactly as its
stdio transport frames a line. The socket is two callables, so the Hub's Starlette
socket, the Relay's websockets connection and an in-memory pair all fit.

Everything a Relay sends is client-controlled data: the Hub keeps its own allowlist,
cluster and namespace checks, redaction and caps on it (ADR 0002).
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import anyio
import httpx
import websockets
from fastmcp import Client, FastMCP
from fastmcp.client.transports.base import ClientTransport
from fastmcp.client.transports.memory import _enter_server_lifespan, _lowlevel_of
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp import ClientSession, types
from mcp.shared.message import SessionMessage
from mcp.types import TextContent, ToolAnnotations
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from aiops_agent import contracts, usage
from aiops_agent.contracts import Contract
from aiops_agent.servers import kubernetes, prometheus

log = logging.getLogger("aiops.relay")

Send = Callable[[str], Awaitable[None]]
Receive = Callable[[], Awaitable[str | None]]  # None: the socket closed
MAX_FRAME = 4 * 1024 * 1024  # characters: tool output is capped well below this


class FrameTooLarge(ValueError):
    pass


@asynccontextmanager
async def bridge(send: Send, receive: Receive) -> AsyncIterator[tuple[Any, Any]]:
    """MCP's (read, write) streams over a socket. A frame that isn't one JSON-RPC
    message, or is too large, reaches the session as an Exception, as mcp's stdio
    transport does with a bad line: it never ends the connection by itself."""
    read_writer, read = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    write, write_reader = anyio.create_memory_object_stream[SessionMessage](0)

    async def inbound() -> None:
        async with read_writer:
            while (frame := await receive()) is not None:
                if len(frame) > MAX_FRAME:
                    await read_writer.send(FrameTooLarge(f"a frame of {len(frame)} characters"))
                    continue
                try:
                    message = types.jsonrpc_message_adapter.validate_json(frame, by_name=False)
                except ValueError as e:
                    await read_writer.send(e)
                    continue
                await read_writer.send(SessionMessage(message))

    async def outbound() -> None:
        async with write_reader:
            async for m in write_reader:
                await send(m.message.model_dump_json(by_alias=True, exclude_unset=True))

    async with anyio.create_task_group() as tg:
        tg.start_soon(inbound)
        tg.start_soon(outbound)
        try:
            yield read, write
        finally:
            tg.cancel_scope.cancel()


async def serve(server: FastMCP, send: Send, receive: Receive) -> None:
    """The Relay's side: run `server` over the socket until it closes.
    ponytail: fastmcp 4.1 has no public way to serve over given streams; this is what its
    own in-memory transport does (exact pins; the bridge tests break on a bump)."""
    lowlevel = _lowlevel_of(server)
    async with _enter_server_lifespan(server=server), bridge(send, receive) as (read, write):
        await lowlevel.run(read, write, lowlevel.create_initialization_options())


class RelayTransport(ClientTransport):
    """The Hub's side: a fastmcp Client over a Relay's socket."""

    def __init__(self, send: Send, receive: Receive) -> None:
        self.send, self.receive = send, receive

    @asynccontextmanager
    async def connect_session(self, **session_kwargs: Any) -> AsyncIterator[ClientSession]:
        session_kwargs.pop("transport_options", None)
        async with (
            bridge(self.send, self.receive) as (read, write),
            ClientSession(read, write, **session_kwargs) as session,
        ):
            yield session


# --- the Hub's side: who a Relay is, and its live connection ------------------------------

Who = tuple[str, str]  # (contract id, cluster)


def tokens(by_id: dict[str, Contract]) -> list[tuple[bytes, Who]]:
    """Each Relay cluster's token, as its sha256 and whom it names. ValueError: one
    that's too short or names two clusters."""
    out: list[tuple[bytes, Who]] = []
    for c in by_id.values():
        for cl in c.clusters:
            if cl.via != "relay":
                continue
            assert cl.relay_token_secret  # the schema requires it for via: relay
            token = c.secret(cl.relay_token_secret).get_secret_value()
            if len(token) < 32:
                raise ValueError(f"{c.id}/{cl.name}: its Relay token is too short (32+ characters)")
            digest = hashlib.sha256(token.encode()).digest()
            if any(hmac.compare_digest(digest, d) for d, _ in out):
                raise ValueError(f"{c.id}/{cl.name}: its Relay token is another Relay's")
            out.append((digest, (c.id, cl.name)))
    return out


def who(authorization: str, known: list[tuple[bytes, Who]]) -> Who | None:
    """Whom a `Bearer <token>` names, or None. Every token is compared, in constant time:
    which one matched, or that none did, takes the same time."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    digest = hashlib.sha256(token.encode()).digest()
    found = None
    for d, named in known:
        if hmac.compare_digest(digest, d):
            found = named
    return found


@dataclass
class Live:
    client: Client[Any]
    close: Callable[[], Awaitable[None]]
    since: float


class Relays:
    """The connected Relays, by (contract, cluster): only the token's lookup puts one
    here, never anything the Relay sends. A new connection with the same token
    replaces the old one (a Relay that restarted before the Hub saw it go)."""

    def __init__(self) -> None:
        self.live: dict[Who, Live] = {}

    def get(self, contract_id: str, cluster: str) -> Client[Any] | None:
        found = self.live.get((contract_id, cluster))
        return found.client if found else None

    async def hold(
        self, named: Who, send: Send, receive: Receive, close: Callable[[], Awaitable[None]]
    ) -> None:
        """Serve one Relay's connection until it closes; its MCP session opens first."""
        closed = anyio.Event()

        async def until_closed() -> str | None:
            frame = await receive()
            if frame is None:
                closed.set()
            return frame

        async with Client(RelayTransport(send, until_closed)) as client:
            me = Live(client, close, time.time())
            old = self.live.get(named)
            self.live[named] = me
            log.info("relay %s/%s connected", *named)
            if old is not None:
                await old.close()
            try:
                await closed.wait()
            finally:
                if self.live.get(named) is me:
                    del self.live[named]
                log.info("relay %s/%s disconnected", *named)


OFFLINE = "Relay offline"
# The tools a Relay answers for its cluster: the same names on the Hub and the Relay.
FORWARDED = frozenset(
    {f"kubernetes_{t}" for t in kubernetes.ACCESS} | {f"prometheus_{t}" for t in prometheus.ACCESS}
)


class RelayOffline(RuntimeError):
    """A Run called a Relay that isn't connected, or didn't answer in time."""


class Forward(Middleware):
    """The Hub's side of a call to a Relay's cluster (slice 3.3a): the Hub's own cluster
    and namespace check, then the same call on that cluster's live Relay. The tools are
    the Hub's own (its list, schemas, approval gate); nothing a Relay offers is ever
    listed, so `hub_promql_*` is never the agent's. A call to another cluster, or any
    other tool (a Sizing's takes a cluster too), passes by untouched."""

    def __init__(self, contract: Contract, relays: Relays, seconds: float) -> None:
        self.contract_id, self.relays, self.seconds = contract.id, relays, seconds
        self.clusters = {c.name: set(c.namespaces) for c in contract.clusters if c.via == "relay"}
        self.gitops = {c.name: set(c.gitops_namespaces) for c in contract.clusters}

    def within(self, cluster: str, row: Any) -> bool:
        """A change the Contract may see: every namespace it names is one of the
        cluster's (a GitOps notice: one of its GitOps namespaces)."""
        where = row.get("namespace") if isinstance(row, dict) else None
        if not isinstance(where, str):
            return False
        allowed = self.gitops[cluster] if "gitops" in row else self.clusters[cluster]
        return set(where.split(", ")) <= allowed

    async def on_call_tool(self, context: MiddlewareContext[Any], call_next: Any) -> Any:
        name, args = context.message.name, context.message.arguments or {}
        cluster = args.get("cluster")
        if name not in FORWARDED or not isinstance(cluster, str) or cluster not in self.clusters:
            return await call_next(context)
        if "namespace" in args and args["namespace"] not in self.clusters[cluster]:
            raise ToolError(
                f"namespace {args['namespace']!r} is not allowed in cluster {cluster!r}; "
                f"allowed: {sorted(self.clusters[cluster])}"
            )
        client = self.relays.get(self.contract_id, cluster)
        if client is None:
            raise ToolError(f"{OFFLINE}: cluster {cluster!r} has no Relay connected")
        try:
            with anyio.fail_after(self.seconds):
                result = await client.call_tool(name, args, raise_on_error=False)
        except TimeoutError:
            raise ToolError(
                f"{OFFLINE}: cluster {cluster!r}'s Relay didn't answer in {self.seconds:g} s"
            ) from None
        except Exception as e:  # the connection ended under the call
            raise ToolError(f"{OFFLINE}: cluster {cluster!r}'s Relay: {type(e).__name__}") from None
        if name == "kubernetes_recent_changes" and not result.is_error:
            # It takes no namespace: the Relay reads what it allows, which may be more
            # than the Contract does, so the Hub keeps only the Contract's.
            rows = (result.structured_content or {}).get("result")
            if not isinstance(rows, list):
                raise ToolError(f"cluster {cluster!r}'s Relay sent changes that aren't a list")
            kept = [r for r in rows if self.within(cluster, r)]
            return ToolResult([TextContent(type="text", text=json.dumps(kept))], {"result": kept})
        return ToolResult(result.content, result.structured_content, is_error=result.is_error)


# --- the Relay's side ---------------------------------------------------------------------


async def dial(url: str, token: str, server: FastMCP) -> None:
    """Connect to the Hub and serve `server` over the socket until it closes."""
    headers = {"Authorization": f"Bearer {token}"}
    async with websockets.connect(url, additional_headers=headers, max_size=MAX_FRAME) as ws:

        async def receive() -> str | None:
            try:
                frame = await ws.recv()
            except websockets.ConnectionClosed:
                return None
            return frame if isinstance(frame, str) else None  # a binary frame ends it

        await serve(server, ws.send, receive)


class RelaySettings(BaseSettings):
    """The Relay's own configuration, set by the client in its manifest (slice 3.2)."""

    model_config = SettingsConfigDict(env_prefix="AIOPS_RELAY_")

    hub: str  # wss://<the Hub's domain>/relay
    token: SecretStr
    cluster: str  # its name in the Contract
    namespaces: list[str]  # JSON, as its RoleBindings grant
    gitops_namespaces: list[str] = []
    prometheus_url: str | None = None  # inside the client's network
    prometheus_token: SecretStr | None = None
    writes: bool = False  # the client's own switch: no write tool exists without it
    tool_output_limit: int = 8000


def relay_server(
    s: RelaySettings,
    apis: dict[str, tuple[Any, ...]] | None = None,
    http: httpx.Client | None = None,
) -> FastMCP:
    """What the Relay serves: its cluster's Kubernetes tools (write tools only when the
    client turns writes on), its Prometheus tools, and the Hub's own PromQL as
    `hub_promql_*`, which the Hub never puts on the agent's list. Tool names are the
    Hub's own (`kubernetes_list_pods`...). apis, http: fakes, for tests."""
    cluster: dict[str, Any] = {"name": s.cluster, "namespaces": s.namespaces, "in_cluster": True}
    cluster["gitops_namespaces"] = s.gitops_namespaces
    k8s = {"name": "kubernetes", "enable_actions": s.writes}
    c = contracts.build(
        {"id": "relay", "name": "relay", "clusters": [cluster], "integrations": [k8s]}
    )
    k8s_integration = c.integrations[0]
    assert isinstance(k8s_integration, contracts.Kubernetes)
    root = FastMCP(f"aiops-relay-{s.cluster}")
    tools = kubernetes.build_server(c, k8s_integration, s.tool_output_limit, apis)
    root.mount(tools, namespace="kubernetes")
    if s.prometheus_url:
        store = {s.cluster: (s.prometheus_url, s.prometheus_token)}
        tested = {s.cluster: http} if http else None
        root.mount(prometheus.build_server(store, True, tested), namespace="prometheus")
        target = usage.Target(s.cluster, s.prometheus_url, s.prometheus_token, {}, s.namespaces)
        prom = usage.Prom(target, http)

        @root.tool(annotations=ToolAnnotations(readOnlyHint=True))
        async def hub_promql_instant(promql: str, at: float) -> list[dict[str, Any]]:
            """The Hub's own query (Sizings, prices, Health): never the agent's."""
            return await asyncio.to_thread(prom.instant, promql, at)

        @root.tool(annotations=ToolAnnotations(readOnlyHint=True))
        async def hub_promql_range(
            promql: str, start: float, end: float, step: int
        ) -> list[dict[str, Any]]:
            """The Hub's own range query: never the agent's."""
            return await asyncio.to_thread(prom.range, promql, start, end, step)

    return root


async def run(
    s: RelaySettings,
    server: FastMCP,
    connect: Callable[[str, str, FastMCP], Awaitable[None]] = dial,
    sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Dial the Hub and serve, forever: after a refusal, a dropped connection or the
    Hub going away, wait and dial again, 1 s doubling to a minute, back to 1 s once
    a connection held (a token the Hub refuses keeps retrying, slowly)."""
    wait = 1.0
    while True:
        started = clock()
        try:
            await connect(s.hub, s.token.get_secret_value(), server)
            why = "the Hub closed the connection"
        except websockets.InvalidStatus as e:
            why = f"the Hub refused the connection ({e.response.status_code}): check the token"
        except (OSError, websockets.WebSocketException) as e:
            why = f"no connection to the Hub: {type(e).__name__}"
        if clock() - started > 60:
            wait = 1.0
        log.warning("relay %s: %s; dialing again in %.0f s", s.cluster, why, wait)
        await sleep(wait)
        wait = min(wait * 2, 60.0)
