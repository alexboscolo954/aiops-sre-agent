"""The Relay's connection (slice 3.1): MCP served by the Relay over a socket it dials,
the token binding it to one Contract's cluster, and a Relay's cluster never reached
Direct."""

import logging
import socket
from collections.abc import Callable
from typing import Any

import anyio
import pytest
import uvicorn
import websockets
from fastmcp import Client, FastMCP
from pydantic import SecretStr, ValidationError

from aiops_agent import contracts, relay, usage
from aiops_agent.api import create_app
from aiops_agent.config import Settings
from aiops_agent.servers import kubernetes
from tests.conftest import make_contract, scripted

A_TOKEN = "a" * 40
B_TOKEN = "b" * 40


def relayed(contract_id: str, token: str, **extra: Any) -> contracts.Contract:
    """A Contract with a Direct cluster `test` and a Relay cluster `edge`."""
    data = {
        "id": contract_id,
        "name": contract_id,
        "clusters": [
            {"name": "test", "context": "test", "namespaces": ["shop"]},
            {"name": "edge", "namespaces": ["shop"], "via": "relay", "relay_token_secret": "r"},
        ],
        "integrations": [{"name": "kubernetes"}],
        **extra,
    }
    return contracts.build(data, secrets={"r": SecretStr(token)})


async def until(ready: Callable[[], bool]) -> None:
    """Poll: the registry and uvicorn have nothing to wait on."""
    with anyio.fail_after(10):
        while not ready():  # noqa: ASYNC110
            await anyio.sleep(0.01)


def tools_server(calls: list[str] | None = None) -> FastMCP:
    server = FastMCP("kubernetes")

    @server.tool
    def list_pods(namespace: str) -> str:
        if calls is not None:
            calls.append(namespace)
        return f"pods in {namespace}"

    return server


# --- the Contract: a Relay's cluster -------------------------------------------------------


def test_a_relay_cluster_names_its_token_and_none_of_the_hubs_credentials() -> None:
    base = {"name": "edge", "namespaces": ["shop"], "via": "relay"}
    with pytest.raises(ValidationError, match="via: relay needs relay_token_secret"):
        contracts.Cluster.model_validate(base)
    for field, value in (
        ("context", "edge"),
        ("in_cluster", True),
        ("kubeconfig_secret", "k"),
        ("allow_exec", True),
        ("prometheus_url", "http://p:9090"),
    ):
        with pytest.raises(ValidationError, match="the Relay holds these"):
            contracts.Cluster.model_validate({**base, "relay_token_secret": "t", field: value})
    with pytest.raises(ValidationError, match="relay_token_secret is for via: relay"):
        contracts.Cluster.model_validate(
            {"name": "x", "namespaces": ["a"], "context": "x", "relay_token_secret": "t"}
        )
    ok = contracts.Cluster.model_validate(
        {**base, "relay_token_secret": "t", "prometheus_labels": {"cluster": "edge"}}
    )
    assert ok.via == "relay" and ok.context is None


def test_the_hub_never_reaches_a_relay_cluster_direct() -> None:
    c = relayed("acme", A_TOKEN, integrations=[
        {"name": "kubernetes"}, {"name": "prometheus", "url": "http://shared:9090"},
    ])  # fmt: skip
    assert [cl.name for cl in c.direct_clusters] == ["test"]
    assert "r" in c.secret_refs()  # checked like every secret
    assert [t.cluster for t in usage.targets(c)] == ["test"]  # not even the shared URL
    edge = next(cl for cl in c.clusters if cl.name == "edge")
    with pytest.raises(RuntimeError, match="via its Relay"):
        kubernetes.api_client(edge, c)  # it has no context: the default would be the Hub's
    probes = [label for label, _, _ in __import__("aiops_agent.agent").agent.probes(c)]
    assert "kubernetes test" in probes and "kubernetes edge" not in probes


# --- tokens -----------------------------------------------------------------------------


def test_each_token_names_one_contracts_cluster() -> None:
    known = relay.tokens({"acme": relayed("acme", A_TOKEN), "bank": relayed("bank", B_TOKEN)})
    assert relay.who(f"Bearer {A_TOKEN}", known) == ("acme", "edge")
    assert relay.who(f"bearer {B_TOKEN}", known) == ("bank", "edge")
    assert relay.who(f"Bearer {A_TOKEN}x", known) is None
    assert relay.who(A_TOKEN, known) is None  # no scheme
    assert relay.who("Bearer ", known) is None
    assert relay.who(f"Basic {A_TOKEN}", known) is None
    with pytest.raises(ValueError, match="another Relay's"):
        relay.tokens({"acme": relayed("acme", A_TOKEN), "bank": relayed("bank", A_TOKEN)})
    with pytest.raises(ValueError, match="too short"):
        relay.tokens({"acme": relayed("acme", "x" * 31)})
    assert relay.tokens({"acme": make_contract()}) == []  # no Relay cluster


# --- the bridge, in memory --------------------------------------------------------------


def pipe() -> tuple[Any, Any, Any, Any]:
    """(hub send, hub receive, relay send, relay receive) over two queues."""
    to_relay_w, to_relay_r = anyio.create_memory_object_stream[str | None](10)
    to_hub_w, to_hub_r = anyio.create_memory_object_stream[str | None](10)
    return to_relay_w.send, to_hub_r.receive, to_hub_w.send, to_relay_r.receive


@pytest.mark.anyio
async def test_mcp_runs_over_the_bridge_and_a_bad_frame_ends_nothing() -> None:
    hub_send, hub_receive, relay_send, relay_receive = pipe()
    calls: list[str] = []
    async with anyio.create_task_group() as tg:
        tg.start_soon(relay.serve, tools_server(calls), relay_send, relay_receive)
        async with Client(relay.RelayTransport(hub_send, hub_receive)) as c:
            assert [t.name for t in await c.list_tools()] == ["list_pods"]
            r = await c.call_tool("list_pods", {"namespace": "shop"})
            assert r.content[0].text == "pods in shop"  # type: ignore[union-attr]
            await hub_send('{"jsonrpc": "2.0", "garbage"')  # not one JSON-RPC message
            huge = "x" * relay.MAX_FRAME  # one valid call, in a frame over the limit
            meta = (  # the envelope mcp's modern protocol wants on every request
                '"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28", '
                '"io.modelcontextprotocol/clientCapabilities": {}}'
            )
            await hub_send(
                '{"jsonrpc": "2.0", "id": 99, "method": "tools/call", "params": '
                f'{{"name": "list_pods", "arguments": {{"namespace": "{huge}"}}, {meta}}}}}'
            )
            await relay_send("not json")  # from the Relay: client-controlled
            r = await c.call_tool("list_pods", {"namespace": "web"})
            assert r.content[0].text == "pods in web"  # type: ignore[union-attr]
        tg.cancel_scope.cancel()
    assert calls == ["shop", "web"]  # the oversized call never ran


@pytest.mark.anyio
async def test_a_new_connection_replaces_the_old_and_a_closed_one_leaves() -> None:
    relays = relay.Relays()
    closed: list[str] = []

    async def connect(name: str, tg: Any) -> Any:
        hub_send, hub_receive, relay_send, relay_receive = pipe()
        tg.start_soon(relay.serve, tools_server(), relay_send, relay_receive)

        async def close() -> None:
            closed.append(name)
            await relay_send(None)  # the socket closes: the Hub's receive sees None

        tg.start_soon(relays.hold, ("acme", "edge"), hub_send, hub_receive, close)
        await until(
            lambda: (x := relays.live.get(("acme", "edge"))) is not None and x.close is close
        )
        return close

    async with anyio.create_task_group() as tg:
        await connect("first", tg)
        assert relays.get("bank", "edge") is None
        second = await connect("second", tg)
        assert closed == ["first"]  # the old one is closed for the new
        r = await relays.get("acme", "edge").call_tool(  # type: ignore[union-attr]
            "list_pods", {"namespace": "shop"}
        )
        assert r.content[0].text == "pods in shop"  # type: ignore[union-attr]
        await second()
        await until(lambda: relays.get("acme", "edge") is None)
        tg.cancel_scope.cancel()


# --- over a real websocket, into the Hub ------------------------------------------------


def hub(
    settings: Settings,
    database_url: str,
    *contracts_: contracts.Contract,
    approver: str = "approver-token",
) -> Any:
    settings.database_url = SecretStr(database_url)
    settings.approver_token = SecretStr(approver)
    by_id = {c.id: c for c in contracts_}
    return create_app(settings, scripted(), lambda c: None, by_id)  # type: ignore[arg-type,return-value]


@pytest.mark.anyio
async def test_a_relay_dials_the_hub_and_serves_only_its_own_cluster(
    settings: Settings, database_url: str, caplog: Any
) -> None:
    caplog.set_level(logging.INFO)
    app = hub(settings, database_url, relayed("acme", A_TOKEN), relayed("bank", B_TOKEN))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    url = f"ws://127.0.0.1:{sock.getsockname()[1]}/relay"
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    relays: relay.Relays = app.state.relays
    async with anyio.create_task_group() as tg:
        tg.start_soon(lambda: server.serve(sockets=[sock]))
        await until(lambda: server.started)
        refused = []
        for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": A_TOKEN}):
            with pytest.raises(websockets.InvalidStatus) as e:
                await websockets.connect(url, additional_headers=headers)
            refused.append(e.value.response.status_code)
        assert refused == [403, 403, 403] and relays.live == {}
        tg.start_soon(relay.dial, url, A_TOKEN, tools_server())
        await until(lambda: relays.get("acme", "edge") is not None)
        r = await relays.get("acme", "edge").call_tool(  # type: ignore[union-attr]
            "list_pods", {"namespace": "shop"}
        )
        assert r.content[0].text == "pods in shop"  # type: ignore[union-attr]
        assert list(relays.live) == [("acme", "edge")]  # A's token serves A only
        server.should_exit = True
        tg.cancel_scope.cancel()
    assert A_TOKEN not in caplog.text and "relay acme/edge connected" in caplog.text


def test_a_relay_token_is_no_other_token(settings: Settings, database_url: str) -> None:
    with pytest.raises(RuntimeError, match="a Relay token is the approver token"):
        hub(settings, database_url, relayed("acme", A_TOKEN), approver=A_TOKEN)
    hooked = relayed("acme", A_TOKEN, webhook_token_sha256=contracts.token_hash(B_TOKEN))
    with pytest.raises(RuntimeError, match="bank/edge: its Relay token is 'acme''s webhook"):
        hub(settings, database_url, hooked, relayed("bank", B_TOKEN))
    with pytest.raises(RuntimeError, match="another Relay's"):
        hub(settings, database_url, relayed("acme", A_TOKEN), relayed("bank", A_TOKEN))
