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
async def test_recent_changes_lists_only_the_contracts_own_namespaces(
    two_contracts: Contracts, settings: Settings, fake_cluster: Any
) -> None:
    """demo-shop and demo-bank share one physical cluster: shop's timeline never lists
    bank's namespace, and shop can't ask for bank's cluster."""
    shop = tools_for(two_contracts["demo-shop"], settings, fake_cluster)
    async with Client(shop.mcp) as client:
        await client.call_tool("kubernetes_recent_changes", {"cluster": "kind"})
        with pytest.raises(ToolError, match="not one of this Contract's clusters"):
            await client.call_tool("kubernetes_recent_changes", {"cluster": "bank-kind"})
    apps = fake_cluster[1]
    listed = {c.args[0] for c in apps.list_namespaced_replica_set.call_args_list}
    assert listed == set(two_contracts["demo-shop"].clusters[0].namespaces)
    assert "bank" not in listed
    apps.list_replica_set_for_all_namespaces.assert_not_called()


@pytest.mark.anyio
async def test_shared_gitops_namespaces_show_only_the_contracts_own_deploys(
    two_contracts: Contracts, settings: Settings, fake_cluster: Any
) -> None:
    """argocd and flux-system are shared by every team on the cluster: demo-shop sees
    its Applications and Kustomizations, never bank's, nor one that spans both, nor
    one that deploys to another cluster."""
    from tests.test_kubernetes_server import ago, app, fake_custom

    shop = two_contracts["demo-shop"]
    assert shop.clusters[0].gitops_namespaces == ["argocd", "flux-system"]
    history = [{"revision": "r1", "deployedAt": ago(5)}]
    bank_ks = {
        "metadata": {"name": "bank-ledger", "namespace": "flux-system"},
        "spec": {"targetNamespace": "bank"},
        "status": {"history": [{"firstReconciled": ago(3), "metadata": {"revision": "bank@1"}}]},
    }
    # Another cluster's orders namespace (where another Contract may run): its
    # objects sit in this cluster's flux-system but deploy through a kubeconfig.
    remote = {"kubeConfig": {"secretRef": {"name": "other-cluster"}}, "targetNamespace": "orders"}
    elsewhere_ks = {
        "metadata": {"name": "elsewhere-ks", "namespace": "flux-system"},
        "spec": remote,
        "status": {"history": [{"firstReconciled": ago(2), "metadata": {"revision": "x@1"}}]},
    }
    elsewhere_hr = {
        "metadata": {"name": "elsewhere-hr", "namespace": "flux-system"},
        "spec": remote,
        "status": {"history": [{"version": 1, "namespace": "orders", "lastDeployed": ago(2)}]},
    }
    unnamed = app("unnamed-dest", "orders", history=history)
    del unnamed["spec"]["destination"]["server"]
    custom = fake_custom(
        {
            ("argocd", "applications"): [
                app("orders-inventory", "orders", history=history),
                app("bank-vault", "bank", history=history),
                app("spans", "orders", history=history, resources=[{"namespace": "bank"}]),
                unnamed,
            ],
            ("flux-system", "kustomizations"): [bank_ks, elsewhere_ks],
            ("flux-system", "helmreleases"): [elsewhere_hr],
        }
    )
    tb = agent.build_mcp(shop, settings, {"kind": (*fake_cluster, custom)})
    async with Client(tb.mcp) as client:
        result = await client.call_tool("kubernetes_recent_changes", {"cluster": "kind"})
    out = result.structured_content["result"]
    assert [c["argocd_application"] for c in out] == ["orders-inventory"]
    for trace in ("bank", "spans", "elsewhere", "unnamed"):
        assert trace not in json.dumps(out)


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
    two_contracts: Contracts,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    fake_cluster: Any,
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
        async with Client(tools_for(mine, settings, fake_cluster).mcp) as client:
            result = await client.call_tool("x_environment", {})
        seen[cid] = json.loads(result.content[0].text)
    for cid, env in seen.items():
        assert env["TOKEN"] == two_contracts[cid].secret("prometheus-token").get_secret_value()
        assert not any(name.startswith("AIOPS_") for name in env), env
        assert "hub-only-model-key" not in json.dumps(env)
    assert seen["demo-shop"]["TOKEN"] != seen["demo-bank"]["TOKEN"]


@pytest.mark.anyio
async def test_a_stored_result_is_readable_only_in_its_own_investigation(
    two_contracts: Contracts, settings: Settings, fake_cluster: Any
) -> None:
    """One checkpoint store for every Contract, as in the Hub: demo-bank's Investigation
    asking for demo-shop's stored result id gets nothing of it."""
    from kubernetes import client as k
    from langgraph.checkpoint.memory import InMemorySaver

    from tests.conftest import REPORT, call, crashlooping_pod, scripted
    from tests.test_agent import ALERT, agent_result_id

    pods = [crashlooping_pod() for _ in range(60)]  # a listing far over the limit
    pods[-1].metadata.name = "shop-only-pod"
    fake_cluster[0].list_namespaced_pod.return_value = k.V1PodList(items=pods)
    settings.tool_output_limit = 1000
    rid = agent_result_id("s1")
    saver = InMemorySaver(serde=agent.CHECKPOINT_SERDE)
    where = {"cluster": "kind", "namespace": "demo"}
    shop = scripted(
        call("kubernetes_list_pods", "s1", **where), call("TriageReport", "s2", **REPORT)
    )
    async with agent.open_agent(
        settings, tools_for(two_contracts["demo-shop"], settings, fake_cluster), shop, saver
    ) as a:
        await agent.start(a, ALERT, "shop-1")
        state = await a.aget_state({"configurable": {"thread_id": "shop-1"}})
        assert "shop-only-pod" in state.values["spilled"][rid]
    bank = scripted(
        call("read_more", "b1", result_id=rid, grep="shop-only"),
        call("TriageReport", "b2", **REPORT),
    )
    async with agent.open_agent(
        settings, tools_for(two_contracts["demo-bank"], settings, fake_cluster), bank, saver
    ) as a:
        await agent.start(a, ALERT, "bank-1")
        state = await a.aget_state({"configurable": {"thread_id": "bank-1"}})
    answer = next(str(m.content) for m in state.values["messages"] if m.type == "tool")
    assert answer == f"no stored result {rid!r} in this Investigation; ids: []"
    assert "shop-only" not in json.dumps([str(m.content) for m in state.values["messages"]])


@pytest.mark.anyio
async def test_an_alert_group_never_joins_another_contracts_triage(
    two_contracts: Contracts, database_url: str
) -> None:
    """Identical labels on the same physical cluster: demo-bank's group finds no open
    Triage of demo-shop's to join."""
    from aiops_agent import related
    from aiops_agent.models import AlertGroup, Investigation
    from aiops_agent.store import Store, connect, now

    labels = {"alertname": "Errors", "cluster": "kind", "service": "ledger"}
    group = {
        "status": "firing",
        "groupKey": "g",
        "commonLabels": labels,
        "alerts": [{"status": "firing", "labels": labels}],
    }
    async with connect(database_url) as pool:
        store = Store(pool)
        await store.migrate()
        shop = Investigation(
            id="shop-t",
            contract_id="demo-shop",
            title="t",
            group_key="other",
            started=now(),
            input=group,
        )
        await store.insert(shop)
        assert [t.id for t in await store.open_triages("demo-shop", now() - 60, "g")] == ["shop-t"]
        candidates = await store.open_triages("demo-bank", now() - 60, "g")
    assert candidates == []
    bank = two_contracts["demo-bank"]
    assert related.find(AlertGroup.model_validate(group), candidates, bank.related) is None


@pytest.mark.anyio
async def test_a_related_group_is_separated_only_through_its_own_triage(
    two_contracts: Contracts, database_url: str
) -> None:
    """demo-bank's related group, named with demo-shop's Triage: not found, and the
    claim inserts nothing (no orphan Triage)."""
    from aiops_agent.models import AlertGroup, Investigation
    from aiops_agent.store import Store, connect, now

    labels = {"alertname": "Errors", "service": "ledger"}
    group = {
        "status": "firing",
        "groupKey": "g",
        "commonLabels": labels,
        "alerts": [{"status": "firing", "labels": labels}],
    }
    async with connect(database_url) as pool:
        store = Store(pool)
        await store.migrate()
        shop, bank = (
            Investigation(id=f"{c}-t", contract_id=c, title="t", group_key="g0", started=now())
            for c in ("demo-shop", "demo-bank")
        )
        await store.insert(shop)
        await store.insert(bank)
        rid = await store.add_related(
            bank.id,
            "demo-bank",
            AlertGroup.model_validate(group),
            {"service": "ledger"},
            False,
            now(),
        )
        assert await store.related_group(rid, shop.id) is None
        new = Investigation(id="new", contract_id="demo-shop", title="t", started=now())
        assert not await store.separate(rid, shop.id, new)
        assert await store.get("new") is None
        assert (await store.related_group(rid, bank.id) or {})["separate_id"] is None


@pytest.mark.anyio
async def test_past_incidents_never_cross_contracts(
    two_contracts: Contracts, settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    """The same words in both Contracts' past Reports: each finds and reads only its own."""
    from aiops_agent.models import Investigation
    from aiops_agent.store import Store, connect, now
    from tests.conftest import REPORT

    async with connect(database_url) as pool:
        store = Store(pool)
        await store.migrate()
        for cid in two_contracts:
            report = {**REPORT, "summary": "ledger OOMKilled: batch size unset"}
            t = Investigation(
                id=f"{cid}-past", contract_id=cid, title="t", status="done", started=now(),
                report=report,
            )  # fmt: skip
            await store.insert(t)
        for cid, c in two_contracts.items():
            apis = {cl.name: fake_cluster for cl in c.clusters}
            tb = agent.build_mcp(c, settings, apis, store=store)
            other = next(o for o in two_contracts if o != cid)
            async with Client(tb.mcp) as client:
                found = await client.call_tool("incidents_search", {"keywords": "ledger batch"})
                assert [i["id"] for i in found.structured_content["incidents"]] == [f"{cid}-past"]
                assert (await client.call_tool("incidents_read", {"id": f"{cid}-past"})).data
                with pytest.raises(ToolError, match="no past Report"):
                    await client.call_tool("incidents_read", {"id": f"{other}-past"})


@pytest.mark.anyio
async def test_teachings_never_cross_contracts(two_contracts: Contracts, database_url: str) -> None:
    """Each Contract's approved Teachings are its own, and one Contract's Teaching can't
    be decided or retired as another's."""
    from aiops_agent.store import Store, connect

    async with connect(database_url) as pool:
        store = Store(pool)
        await store.migrate()
        ids = {}
        for cid in two_contracts:
            ids[cid, "approved"] = await store.add_teaching(
                cid, f"{cid} lesson", [], approved_by="x"
            )
            ids[cid, "proposed"] = await store.add_teaching(cid, f"{cid} draft", [])
        for cid in two_contracts:
            other = next(o for o in two_contracts if o != cid)
            assert [t["text"] for t in await store.teachings(cid, "approved")] == [f"{cid} lesson"]
            assert await store.decide_teaching(ids[other, "proposed"], cid, True, "x") is None
            assert not await store.retire_teaching(ids[other, "approved"], cid, "x")
        assert {t["status"] for t in await store.teachings()} == {"approved", "proposed"}
