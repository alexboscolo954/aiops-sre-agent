"""Contract isolation: nothing of one Contract is reachable while working for another.

Every test uses the two synthetic demo Contracts (demo/contracts). Add one here for
each feature that stores, reads or sends Contract data.
"""

import json
import logging
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from aiops_agent import agent, contracts
from aiops_agent.config import Settings

Contracts = dict[str, contracts.Contract]


def tools_for(c: contracts.Contract, settings: Settings, fake_cluster: Any) -> agent.Toolbox:
    return agent.build_mcp(c, settings, {cl.name: fake_cluster for cl in c.clusters})


@pytest.mark.anyio
async def test_each_contract_gets_only_its_own_clusters(
    two_contracts: Contracts, settings: Settings, fake_cluster: Any
) -> None:
    enums = {}
    for cid, c in two_contracts.items():
        async with Client(tools_for(c, settings, fake_cluster).mcp) as client:
            tools = {t.name: t for t in await client.list_tools()}
        enums[cid] = tools["kubernetes_list_pods"].input_schema["properties"]["cluster"]["enum"]
    assert enums == {"demo-shop": ["kind"], "demo-bank": ["bank-kind"]}


@pytest.mark.anyio
async def test_naming_another_contracts_cluster_fails(
    two_contracts: Contracts, settings: Settings, fake_cluster: Any
) -> None:
    shop = tools_for(two_contracts["demo-shop"], settings, fake_cluster)
    async with Client(shop.mcp) as client:
        with pytest.raises(ToolError, match="not one of this Contract's clusters: \\['kind'\\]"):
            await client.call_tool(
                "kubernetes_list_pods", {"cluster": "bank-kind", "namespace": "bank"}
            )
        # Same physical cluster, but demo-shop may only read its own namespace.
        with pytest.raises(ToolError, match="'bank' is not allowed in cluster 'kind'"):
            await client.call_tool("kubernetes_list_pods", {"cluster": "kind", "namespace": "bank"})
    fake_cluster[0].list_namespaced_pod.assert_not_called()


@pytest.mark.anyio
async def test_runbooks_never_cross_contracts(
    two_contracts: Contracts, settings: Settings, fake_cluster: Any
) -> None:
    async def runbooks(cid: str, alert: str, keywords: str) -> tuple[list[str], list[str]]:
        tb = tools_for(two_contracts[cid], settings, fake_cluster)
        async with Client(tb.mcp) as client:
            hit = await client.call_tool("runbooks_runbook_for_alert", {"alertname": alert})
            found = await client.call_tool("runbooks_search_runbooks", {"keywords": keywords})
        mapped = [b["title"] for b in hit.structured_content["runbooks"]]
        return mapped, [b["title"] for b in found.structured_content["result"]]

    shop_mapped, shop_found = await runbooks("demo-shop", "KubePodCrashLooping", "ledger")
    bank_mapped, bank_found = await runbooks("demo-bank", "KubePodCrashLooping", "checkout")
    # A Contract's own Runbook overrides the shared one with the same name.
    assert shop_mapped == ["Crash loop (demo-shop's own)"]
    assert bank_mapped == ["Crash loop (shared)"]
    assert shop_found == [] and bank_found == []


@pytest.mark.anyio
async def test_audit_lines_name_the_contract(
    two_contracts: Contracts,
    settings: Settings,
    fake_cluster: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="aiops.audit")
    bank = tools_for(two_contracts["demo-bank"], settings, fake_cluster)
    async with Client(bank.mcp) as client:
        await client.call_tool(
            "kubernetes_list_pods", {"cluster": "bank-kind", "namespace": "bank"}
        )
    lines = [json.loads(r.message) for r in caplog.records if r.name == "aiops.audit"]
    assert [(line["contract"], line["tool"]) for line in lines] == [
        ("demo-bank", "kubernetes_list_pods")
    ]


def test_each_contract_uses_its_own_prometheus_credentials(
    two_contracts: Contracts, settings: Settings, fake_cluster: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aiops_agent.servers import prometheus

    seen: list[tuple[str, str]] = []

    class Recorder:
        def __init__(self, base_url: str, headers: dict[str, str], **_: Any) -> None:
            seen.append((base_url, headers.get("Authorization", "")))

    monkeypatch.setattr(prometheus.httpx, "Client", Recorder)
    for cid in ("demo-shop", "demo-bank"):
        tools_for(two_contracts[cid], settings, fake_cluster)
    assert seen == [
        ("http://localhost:9090", "Bearer shop-demo-token"),
        ("http://localhost:9091", "Bearer bank-demo-token"),
    ]


@pytest.mark.anyio
async def test_a_question_for_one_contract_cannot_reach_anothers_cluster(
    two_contracts: Contracts, settings: Settings, fake_cluster: Any
) -> None:
    from langchain.messages import ToolMessage

    from tests.conftest import call, scripted

    answer = {"answer": "I can't see bank-kind.", "evidence": [{"source": "x", "finding": "y"}]}
    model = scripted(
        call("kubernetes_list_pods", "q1", cluster="bank-kind", namespace="bank"),
        call("Answer", "q2", **answer),
    )
    shop = tools_for(two_contracts["demo-shop"], settings, fake_cluster)
    async with agent.open_agent(settings, shop, model, kind="question") as a:
        await agent.ask(a, "What runs in bank-kind?", "iso-q")
        state = await a.aget_state({"configurable": {"thread_id": "iso-q"}})
    (result,) = [
        m for m in state.values["messages"] if isinstance(m, ToolMessage) and m.tool_call_id == "q1"
    ]
    assert result.status == "error" and "not one of this Contract's clusters" in str(result.content)
    fake_cluster[0].list_namespaced_pod.assert_not_called()


@pytest.mark.anyio
async def test_a_vendor_process_sees_only_its_own_contracts_secrets(
    two_contracts: Contracts, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each Contract's vendor subprocess gets its own secrets, and none of the Hub's
    environment (model key, approver token, database URL, other Contracts)."""
    import sys
    from pathlib import Path

    from aiops_agent.contracts import Vendor
    from aiops_agent.servers import vendors

    fixture = Path(__file__).parent / "fixtures" / "vendor_server.py"
    monkeypatch.setitem(
        vendors.VENDORS,
        "fixture",
        vendors.Spec((sys.executable, str(fixture)), frozenset({"TOKEN"})),
    )
    monkeypatch.setenv("AIOPS_MODEL_API_KEY", "hub-only-model-key")
    seen = {}
    for cid, c in two_contracts.items():
        vendor = Vendor(
            name="x",
            vendor="fixture",
            env_secrets={"TOKEN": "prometheus-token"},
            tools={"environment": "read"},
        )
        mine = c.model_copy(update={"integrations": [*c.integrations, vendor]})
        async with Client(agent.build_mcp(mine, settings).mcp) as client:
            result = await client.call_tool("x_environment", {})
        seen[cid] = json.loads(result.content[0].text)
    for cid, env in seen.items():
        assert env["TOKEN"] == two_contracts[cid].secret("prometheus-token").get_secret_value()
        assert not any(name.startswith("AIOPS_") for name in env), env
        assert "hub-only-model-key" not in json.dumps(env)
    assert seen["demo-shop"]["TOKEN"] != seen["demo-bank"]["TOKEN"]
