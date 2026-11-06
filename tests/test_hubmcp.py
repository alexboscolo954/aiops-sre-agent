"""The Hub MCP server (slice 11.1a): both doors, each call within one Contract, that
Contract's Data policy on everything returned (errors included), placeholders back
only for the Contract that handed them out, an audit line per call, and none of it in
the Investigation agent's tools."""

import asyncio
import json
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from aiops_agent import agent, cli, contracts, masking, webapp
from aiops_agent.api import create_app
from aiops_agent.config import Settings
from aiops_agent.store import Store, connect
from tests.conftest import make_contract
from tests.test_api import client, scripted
from tests.test_console import OPERATOR
from tests.test_sizing_store import NOW, row, stored
from tests.test_webapp import INTEGRATIONS, seed

TOKEN = "t" * 40
MCP = {"Authorization": f"Bearer {TOKEN}", "Tailscale-User-Login": OPERATOR}
ACCEPT = {"Accept": "application/json, text/event-stream"}
# acme masks its own id and its namespace; bank masks nothing
ACME = {
    "integrations": INTEGRATIONS,
    "data_policy": {"mask": {"terms": ["acme", "shop"]}},
    "secrets": {contracts.MASK_KEY: "k-acme"},
}
TOOLS = {"list_contracts", "sizings", "sizing"}


@pytest.fixture(autouse=True)
def _clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("aiops_agent.api.now", lambda: NOW)


def hub(
    settings: Settings,
    fake_cluster: Any,
    database_url: str,
    clusters_of_bank: bool = False,
    acme_clusters: dict[str, list[str]] | None = None,
) -> TestClient:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    settings.mcp_token = SecretStr(TOKEN)
    clusters = {"test": ["shop"], "edge": ["shop"]} if clusters_of_bank else None
    bank = make_contract(contract_id="bank", integrations=INTEGRATIONS, clusters=clusters)
    acme = {**ACME, "clusters": acme_clusters} if acme_clusters else ACME
    return client(settings, fake_cluster, acme=acme, more={"bank": (bank, fake_cluster)})


def rpc(c: TestClient, method: str, params: dict[str, Any], headers: Any = None) -> Any:
    return c.post(
        "/mcp/",
        headers={**ACCEPT, **(MCP if headers is None else headers)},
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
    )


def call(c: TestClient, tool: str, **args: Any) -> Any:
    """The tool's structured answer, or its error text as {"error": ...}."""
    r = rpc(c, "tools/call", {"name": tool, "arguments": args})
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    if result.get("isError"):
        return {"error": result["content"][0]["text"]}
    content = result["structuredContent"]
    return content.get("result", content)  # a list comes wrapped


def mask(value: str) -> str:
    return masking.Masker(b"k-acme", ["acme", "shop"]).placeholder("name", value)


def seed_run(database_url: str, cid: str, *rows: dict[str, Any]) -> None:
    """One Sizing run at NOW with these rows."""

    async def go() -> None:
        async with connect(database_url) as pool:
            store = Store(pool)
            await store.migrate()
            await stored(store, cid, NOW, {r["cluster"]: None for r in rows}, *rows)

    asyncio.run(go())


# --- the doors -------------------------------------------------------------------------


def test_a_call_needs_the_token_and_a_listed_operators_identity(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    init = {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "t", "version": "1"},
    }
    bearer = {"Authorization": f"Bearer {TOKEN}"}
    with hub(settings, fake_cluster, database_url) as c:
        refused = [
            rpc(c, "initialize", init, h).status_code
            for h in (
                {"Tailscale-User-Login": OPERATOR},  # no token
                {"Authorization": "Bearer approver-token", "Tailscale-User-Login": OPERATOR},
                {"Authorization": f"Bearer {TOKEN}x", "Tailscale-User-Login": OPERATOR},
                bearer,  # no identity: not through tailscale serve
                {**bearer, "Tailscale-User-Login": "mallory@example.com"},
            )
        ]
        ok = rpc(c, "initialize", init, {**MCP, "Host": "hub.tail1234.ts.net"})
        listed = rpc(c, "tools/list", {})
    assert refused == [401, 401, 401, 403, 403]
    assert "result" in ok.json(), ok.text
    assert ok.json()["result"]["serverInfo"]["name"] == "aiops-hub"
    tools = {t["name"]: t for t in listed.json()["result"]["tools"]}
    assert set(tools) == TOOLS
    assert all(t["annotations"]["readOnlyHint"] for t in tools.values())


def test_it_is_off_without_its_token(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    with client(settings, fake_cluster) as c:
        assert rpc(c, "tools/list", {}).status_code == 404


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"console_operators": set()}, "needs AIOPS_CONSOLE_OPERATORS"),
        ({"mcp_token": SecretStr("t" * 31)}, "too short"),
        ({"mcp_token": SecretStr("a" * 32), "approver_token": SecretStr("a" * 32)}, "approver"),
        ({"mcp_token": SecretStr("h" * 32)}, "webhook token is the MCP token"),
    ],
)
def test_it_refuses_to_start_on_a_token_that_would_open_another_door(
    settings: Settings, change: dict[str, Any], error: str
) -> None:
    settings.approver_token = SecretStr("approver-token")
    settings.console_operators = {OPERATOR}
    settings.mcp_token = SecretStr(TOKEN)
    for k, v in change.items():
        setattr(settings, k, v)
    acme = make_contract(webhook_token="h" * 32)
    with pytest.raises(RuntimeError, match=error):
        create_app(settings, scripted(), by_id={"acme": acme})


def test_a_token_of_32_is_enough(settings: Settings, database_url: str) -> None:
    settings.approver_token = SecretStr("approver-token")
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    settings.mcp_token = SecretStr("t" * 32)
    create_app(settings, scripted(), by_id={"acme": make_contract()})


def test_the_agent_never_gets_these_tools(settings: Settings, fake_cluster: Any) -> None:
    c = make_contract(integrations=INTEGRATIONS)
    names = set(agent.build_mcp(c, settings, {"test": fake_cluster}).access)
    assert "kubernetes_list_pods" in names and not names & TOOLS


# --- within one Contract, by its Data policy ---------------------------------------------


def test_contracts_are_listed_masked_by_their_own_policy(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    with hub(settings, fake_cluster, database_url) as c:
        listed = call(c, "list_contracts")
    assert listed == [
        {"id": mask("acme"), "name": mask("acme"), "clusters": ["test"]},
        {"id": "bank", "name": "bank", "clusters": ["test"]},
    ]


def test_sizings_rank_filter_and_mask_and_take_the_placeholder_back(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    risk = {"kind": "oom_killed", "text": "OOM-killed in shop"}
    seed_run(
        database_url,
        "acme",
        row("api", waste={"cpu": 2.0, "memory": 0.0}),
        row("web", waste={"cpu": 3.0, "memory": 0.0}, risks=[risk]),
        row("db", waste={"cpu": 1.0, "memory": 0.0}),
    )
    with hub(settings, fake_cluster, database_url) as c:
        acme = call(c, "list_contracts")[0]["id"]
        ranked = call(c, "sizings", contract=acme, top=2)
        by_real_id = call(c, "sizings", contract="acme", top=2)
        risky = call(c, "sizings", contract=acme, risky=True)
        in_shop = call(c, "sizings", contract=acme, namespace=mask("shop"), cluster="test")
        elsewhere = call(c, "sizings", contract=acme, namespace="other")
        unknown = call(c, "sizings", contract=acme, cluster="nope")
        never = call(c, "sizings", contract="<name-00000000>")
    shop = mask("shop")
    assert [w["workload"] for w in ranked["workloads"]] == [
        f"test/{shop}/Deployment/web",
        f"test/{shop}/Deployment/api",
    ]
    assert ranked == by_real_id and ranked["matching"] == 3
    assert ranked["workloads"][0]["waste"] == {"cpu": "3000m", "memory": "0Mi"}
    assert ranked["workloads"][0]["risks"] == [f"OOM-killed in {shop}"]
    assert ranked["clusters"] == [
        {"cluster": "test", "as_of": "1972-09-27 00:00 UTC", "failing": None, "since": None}
    ]
    assert [w["workload"] for w in risky["workloads"]] == [f"test/{shop}/Deployment/web"]
    assert in_shop["matching"] == 3 and elsewhere["matching"] == 0
    assert unknown == {"error": "cluster 'nope' has no Sizings: one of ['test']"}
    assert never == {"error": "unknown Contract: list_contracts names them"}
    assert "shop" not in json.dumps([ranked, risky, in_shop]) and "acme" not in json.dumps(ranked)


def test_sizings_filter_by_cluster(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    seed_run(database_url, "bank", row("api"), row("web", cluster="edge"))
    with hub(settings, fake_cluster, database_url, clusters_of_bank=True) as c:
        both = call(c, "sizings", contract="bank")
        edge = call(c, "sizings", contract="bank", cluster="edge")
    assert both["matching"] == 2
    assert [w["workload"] for w in edge["workloads"]] == ["edge/shop/Deployment/web"]


def test_one_workloads_sizing_and_its_errors_are_masked_too(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    seed(database_url, ("acme", NOW, row("api")))
    with hub(settings, fake_cluster, database_url) as c:
        call(c, "sizings", contract="acme")  # hands out shop's placeholder
        found = call(
            c, "sizing", contract="acme", cluster="test", namespace=mask("shop"), name="api"
        )
        plain = call(c, "sizing", contract="acme", cluster="test", namespace="shop", name="api-7d")
        refused = call(c, "sizing", contract="acme", cluster="test", namespace="kube", name="api")
    (w,) = found["workloads"]
    assert w["workload"] == f"test/{mask('shop')}/Deployment/api"
    assert plain["workloads"][0]["name"] == "api"  # a pod's name finds its Workload
    assert refused == {
        "error": f"namespace 'kube' is not allowed in cluster 'test'; allowed: ['{mask('shop')}']"
    }


def test_no_term_reaches_the_client_anywhere_in_an_answer(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    """A cluster named after the client, in keys or values, answers or errors: the raw
    HTTP body carries both the structured answer and its text copy."""
    risk = {"kind": "oom_killed", "text": "OOM-killed in shop"}
    seed_run(database_url, "acme", row("api", cluster="acme-east", risks=[risk]))
    with hub(settings, fake_cluster, database_url, acme_clusters={"acme-east": ["shop"]}) as c:

        def raw(tool: str, **args: Any) -> str:
            r = rpc(c, "tools/call", {"name": tool, "arguments": args})
            assert r.status_code == 200
            return r.text

        bodies = [
            raw("list_contracts"),
            raw("sizings", contract="acme"),
            raw("sizing", contract="acme", cluster="acme-east", namespace="shop", name="api"),
            raw("sizings", contract="acme", cluster="nope"),
            raw("sizing", contract="acme", cluster="nope", namespace="shop", name="api"),
            raw("sizing", contract="acme", cluster="acme-east", namespace="kube", name="api"),
        ]
    assert '"isError":true' in bodies[3].replace(" ", "")
    assert "Deployment/api" in bodies[1] and "Deployment/api" in bodies[2]
    for body in bodies:
        assert "acme" not in body.lower() and "shop" not in body.lower(), body


def test_an_unexpected_errors_text_never_reaches_the_client(
    settings: Settings, fake_cluster: Any, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*_: Any) -> Any:
        raise RuntimeError("db at acme.shop.internal is down")

    monkeypatch.setattr(webapp, "workloads_of", broken)
    with hub(settings, fake_cluster, database_url) as c:
        error = call(c, "sizings", contract="acme")["error"]
    assert "acme" not in error and "shop" not in error


# --- isolation --------------------------------------------------------------------------


def test_a_placeholder_comes_back_only_for_the_contract_that_handed_it_out(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    """Same cluster, namespace and Workload names in both Contracts; acme masks."""
    seed(
        database_url, ("acme", NOW, row(policy="acme-only")), ("bank", NOW, row(policy="bank-only"))
    )
    with hub(settings, fake_cluster, database_url) as c:
        acme = call(c, "list_contracts")[0]["id"]
        mine = call(c, "sizings", contract=acme)
        theirs = call(c, "sizings", contract="bank")
        # acme's placeholders mean nothing in bank's calls, its id included
        shop_in_bank = call(c, "sizings", contract="bank", namespace=mask("shop"))
        sizing_in_bank = call(
            c, "sizing", contract="bank", cluster="test", namespace=mask("shop"), name="api"
        )
        not_bank = call(c, "sizings", contract=mask("bank"))
    assert mine["workloads"] and theirs["workloads"]
    assert {x["workload"] for x in theirs["workloads"]} == {"test/shop/Deployment/api"}
    assert shop_in_bank["matching"] == 0
    assert "is not allowed" in sizing_in_bank["error"]
    assert not_bank == {"error": "unknown Contract: list_contracts names them"}


def test_a_placeholder_never_handed_out_stays_as_written(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    """A placeholder the client computed or invented, before any listing: not resolved."""
    seed(database_url, ("acme", NOW, row()))
    with hub(settings, fake_cluster, database_url) as c:
        unresolved = call(c, "sizings", contract=mask("acme"))
    assert unresolved == {"error": "unknown Contract: list_contracts names them"}


# --- audit ------------------------------------------------------------------------------


def test_serve_writes_the_audit_log_to_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Live 11.1a found every aiops INFO line dropped: uvicorn configures only its own."""
    import uvicorn

    hub = logging.getLogger("aiops")
    before = (hub.handlers[:], hub.level)
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    monkeypatch.chdir("/")  # no .env with moved settings here
    try:
        assert cli.main(["serve"]) == 0
        logging.getLogger("aiops.audit").info('{"event": "tool_call", "channel": "mcp"}')
    finally:
        hub.handlers[:], hub.level = before
    assert (
        'INFO:     aiops.audit {"event": "tool_call", "channel": "mcp"}' in capsys.readouterr().err
    )


def test_every_call_is_an_audit_line_with_its_channel_login_and_contract(
    settings: Settings, fake_cluster: Any, database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        caplog.at_level(logging.INFO, logger="aiops.audit"),
        hub(settings, fake_cluster, database_url) as c,
    ):
        acme = call(c, "list_contracts")[0]["id"]
        call(c, "sizings", contract=acme, namespace=mask("shop"))
    lines = [json.loads(r.message) for r in caplog.records if r.name == "aiops.audit"]
    assert [(x["tool"], x["status"]) for x in lines] == [
        ("list_contracts", "ok"),
        ("sizings", "ok"),
    ]
    assert lines[1] == {
        "event": "tool_call",
        "channel": "mcp",
        "login": OPERATOR,
        "contract": mask("acme"),  # as the client wrote it: masked stays masked
        "tool": "sizings",
        "args": {"contract": mask("acme"), "namespace": mask("shop")},
        "status": "ok",
        "ms": lines[1]["ms"],
    }
