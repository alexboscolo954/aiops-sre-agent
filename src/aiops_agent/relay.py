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

import hashlib
import hmac
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import anyio
import websockets
from fastmcp import Client, FastMCP
from fastmcp.client.transports.base import ClientTransport
from fastmcp.client.transports.memory import _enter_server_lifespan, _lowlevel_of
from mcp import ClientSession, types
from mcp.shared.message import SessionMessage

from aiops_agent.contracts import Contract

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
