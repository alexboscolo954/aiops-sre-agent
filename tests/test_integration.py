"""Real MCP tools against the kind demo cluster (`make cluster demo integration`).

Guarded: refuses to run against any context that is not a kind cluster.
"""

import os
from typing import Any

import pytest
from fastmcp import Client, FastMCP

from aiops_agent import agent, contracts
from aiops_agent.config import Settings
from aiops_agent.models import AlertGroup
from aiops_agent.servers import kubernetes
from tests.conftest import call, scripted

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
def live(two_contracts: dict[str, contracts.Contract]) -> contracts.Contract:
    """demo-shop, on the kind demo cluster. Refuses any context that is not kind."""
    for c in two_contracts.values():
        for cluster in c.clusters:
            if not (cluster.context or "").startswith("kind-"):
                pytest.fail(f"integration tests only run against kind, got {cluster.context!r}")
    return two_contracts["demo-shop"]


def k8s(contract: contracts.Contract) -> FastMCP:
    k = next(i for i in contract.integrations if isinstance(i, contracts.Kubernetes))
    return kubernetes.build_server(contract, k, Settings(_env_file=None).tool_output_limit)


async def tool(client: Client, tool_name: str, /, **args: Any) -> Any:  # type: ignore[type-arg]
    result = await client.call_tool(tool_name, args)
    data = result.structured_content
    if isinstance(data, dict) and set(data) == {"result"} and isinstance(data["result"], str):
        return data["result"]  # str-returning tools are wrapped by FastMCP
    return data or result.content[0].text


def by_app(pods: list[dict[str, Any]], app: str) -> list[dict[str, Any]]:
    return [p for p in pods if p["name"].startswith(app)]


async def test_finds_all_three_failures(live: contracts.Contract) -> None:
    async with Client(k8s(live)) as c:
        pods = (await tool(c, "list_pods", cluster="kind", namespace="demo"))["result"]

        crashing = [p for p in by_app(pods, "checkout") if p["restarts"] >= 2]
        assert crashing, pods
        assert crashing[0]["last_terminated"]["app"]["exit_code"] == 1

        reports = by_app(pods, "reports")[0]
        assert reports["last_terminated"]["app"]["terminated"] == "OOMKilled"

        frontend = by_app(pods, "frontend")[0]
        assert frontend["containers"]["web"]["waiting"] in {"ImagePullBackOff", "ErrImagePull"}

        logs = await tool(
            c, "pod_logs", cluster="kind", namespace="demo", name=crashing[0]["name"], previous=True
        )
        assert "DATABASE_URL is not set" in logs

        history = await tool(
            c, "describe_deployment", cluster="kind", namespace="demo", name="checkout"
        )
        revisions = [r["revision"] for r in history["rollout_history"]]
        assert revisions[:2] == ["2", "1"], history
        env = [r["config"]["app"]["env"] for r in history["rollout_history"][:2]]
        assert env == [[], ["DATABASE_URL"]], env  # the bad rollout is visible as a diff

        events = (await tool(c, "get_events", cluster="kind", namespace="demo"))["result"]
        assert any(e["reason"] in {"Failed", "BackOff"} for e in events)


async def test_demo_bank_cannot_read_demo_shops_namespace(
    two_contracts: dict[str, contracts.Contract],
) -> None:
    """Same kind cluster, two Contracts: each reads only its own namespace."""
    async with Client(k8s(two_contracts["demo-bank"])) as c:
        own = await c.call_tool("list_pods", {"cluster": "bank-kind", "namespace": "bank"})
        other = await c.call_tool(
            "list_pods", {"cluster": "bank-kind", "namespace": "demo"}, raise_on_error=False
        )
    assert not own.is_error
    assert other.is_error and "not allowed in cluster 'bank-kind'" in other.content[0].text


async def test_namespace_allowlist_holds_on_a_real_cluster(live: contracts.Contract) -> None:
    async with Client(k8s(live)) as c:
        result = await c.call_tool(
            "list_pods", {"cluster": "kind", "namespace": "kube-system"}, raise_on_error=False
        )
    assert result.is_error and "not allowed" in result.content[0].text


async def test_agent_triage_through_real_tools(live: contracts.Contract) -> None:
    """Scripted model, real tools: proves the whole loop works against a cluster."""
    async with Client(k8s(live)) as c:
        pods = (await tool(c, "list_pods", cluster="kind", namespace="demo"))["result"]
    pod = next(p["name"] for p in by_app(pods, "checkout") if p["restarts"] >= 2)

    report = {
        "summary": "checkout revision 2 crash loops: DATABASE_URL was removed.",
        "category": "bad_rollout",
        "probable_root_cause": "Rollout 2 dropped the DATABASE_URL env var.",
        "confidence": "high",
        "severity": "high",
        "affected": ["demo/deployment/checkout"],
        "evidence": [{"source": "kubernetes_pod_logs", "finding": "DATABASE_URL is not set"}],
        "recommended_actions": ["Roll back checkout to revision 1"],
    }
    model = scripted(
        call("kubernetes_list_pods", "c1", cluster="kind", namespace="demo"),
        call(
            "kubernetes_pod_logs", "c2", cluster="kind", namespace="demo", name=pod, previous=True
        ),
        call(
            "kubernetes_describe_deployment",
            "c3",
            cluster="kind",
            namespace="demo",
            name="checkout",
        ),
        call("TriageReport", "c4", **report),
    )
    alert = AlertGroup.model_validate(
        {
            "status": "firing",
            "commonLabels": {"alertname": "KubePodCrashLooping", "namespace": "demo"},
            "alerts": [{"status": "firing", "labels": {"pod": pod}}],
        }
    )
    hub = Settings(_env_file=None)
    async with agent.open_agent(hub, agent.build_mcp(live, hub), model) as a:
        outcome = await agent.start(a, alert, "it-1")
    assert outcome.report is not None and outcome.report.category == "bad_rollout"
    assert len(outcome.tool_calls) == 4


async def test_recent_changes_finds_the_dependency_rollout(live: contracts.Contract) -> None:
    """The real API: inventory's rollout, what it changed, and only demo-shop's namespaces
    (demo-bank's namespace sits on the same cluster)."""
    async with Client(k8s(live)) as c:
        changes = (await tool(c, "recent_changes", cluster="kind"))["result"]
    rollout = next(
        ch for ch in changes if ch["deployment"] == "inventory" and ch["change"] == "rollout"
    )
    assert rollout["namespace"] == "orders"
    assert rollout["diff"] == {"env_added": {"app": ["API_VERSION"]}}
    assert {ch["namespace"] for ch in changes} == {"demo", "orders"}


async def test_record_eval_fixtures(live: contracts.Contract) -> None:
    """With AIOPS_RECORD_DIR set, save real tool outputs for the eval scenarios."""
    out = os.environ.get("AIOPS_RECORD_DIR")
    if not out:
        pytest.skip("AIOPS_RECORD_DIR not set")
    import json
    from pathlib import Path

    async def namespace(c: Client, ns: str, deployments: tuple[str, ...]) -> dict[str, Any]:
        rec: dict[str, Any] = {}
        pods = (await tool(c, "list_pods", cluster="kind", namespace=ns))["result"]
        rec["kubernetes_list_pods"] = pods
        rec["kubernetes_list_deployments"] = await tool(
            c, "list_deployments", cluster="kind", namespace=ns
        )
        rec["kubernetes_get_events"] = await tool(c, "get_events", cluster="kind", namespace=ns)
        for name in deployments:
            rec[f"deploy:{name}"] = await tool(
                c, "describe_deployment", cluster="kind", namespace=ns, name=name
            )
        for p in pods:
            rec[f"pod:{p['name']}"] = await tool(
                c, "describe_pod", cluster="kind", namespace=ns, name=p["name"]
            )
            for previous in (False, True):
                r = await c.call_tool(
                    "pod_logs",
                    {"cluster": "kind", "namespace": ns, "name": p["name"], "previous": previous},
                    raise_on_error=False,
                )
                rec[f"logs:{p['name']}:{previous}"] = r.content[0].text
        return rec

    async with Client(k8s(live)) as c:
        rec = await namespace(c, "demo", ("checkout", "reports", "frontend"))
        rec["orders"] = await namespace(c, "orders", ("orders-api", "inventory"))
        # Both namespaces in one call: build_scenarios keeps each Scenario's own.
        changes = await tool(c, "recent_changes", cluster="kind")
        rec["kubernetes_recent_changes"] = changes["result"]
    Path(out).mkdir(parents=True, exist_ok=True)
    data = json.dumps(rec, indent=2, default=str)
    (Path(out) / "recording.json").write_text(data)
