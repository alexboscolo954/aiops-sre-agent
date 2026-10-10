"""Real MCP tools against the kind demo cluster (`make cluster demo integration`).

Guarded: refuses to run against any context that is not a kind cluster.
"""

import os
from typing import Any

import pytest
from fastmcp import Client, FastMCP

from aiops_agent import agent
from aiops_agent.config import Settings
from aiops_agent.models import AlertGroup
from aiops_agent.servers import kubernetes
from tests.conftest import call, scripted

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
def live() -> Settings:
    ctx = os.environ.get("AIOPS_KUBE_CONTEXT", "")
    if not ctx.startswith("kind-"):
        pytest.fail(f"integration tests only run against kind clusters, got {ctx!r}")
    return Settings(_env_file=None, kube_context=ctx, namespaces=["demo"])


async def tool(client: Client, tool_name: str, /, **args: Any) -> Any:  # type: ignore[type-arg]
    result = await client.call_tool(tool_name, args)
    data = result.structured_content
    if isinstance(data, dict) and set(data) == {"result"} and isinstance(data["result"], str):
        return data["result"]  # str-returning tools are wrapped by FastMCP
    return data or result.content[0].text


def by_app(pods: list[dict[str, Any]], app: str) -> list[dict[str, Any]]:
    return [p for p in pods if p["name"].startswith(app)]


async def test_finds_all_three_failures(live: Settings) -> None:
    async with Client(kubernetes.build_server(live)) as c:
        pods = (await tool(c, "list_pods", namespace="demo"))["result"]

        crashing = [p for p in by_app(pods, "checkout") if p["restarts"] >= 2]
        assert crashing, pods
        assert crashing[0]["last_terminated"]["app"]["exit_code"] == 1

        reports = by_app(pods, "reports")[0]
        assert reports["last_terminated"]["app"]["terminated"] == "OOMKilled"

        frontend = by_app(pods, "frontend")[0]
        assert frontend["containers"]["web"]["waiting"] in {"ImagePullBackOff", "ErrImagePull"}

        logs = await tool(c, "pod_logs", namespace="demo", name=crashing[0]["name"], previous=True)
        assert "DATABASE_URL is not set" in logs

        history = await tool(c, "describe_deployment", namespace="demo", name="checkout")
        revisions = [r["revision"] for r in history["rollout_history"]]
        assert revisions[:2] == ["2", "1"], history

        events = (await tool(c, "get_events", namespace="demo"))["result"]
        assert any(e["reason"] in {"Failed", "BackOff"} for e in events)


async def test_namespace_allowlist_holds_on_a_real_cluster(live: Settings) -> None:
    async with Client(kubernetes.build_server(live)) as c:
        result = await c.call_tool("list_pods", {"namespace": "kube-system"}, raise_on_error=False)
    assert result.is_error and "not allowed" in result.content[0].text


async def test_agent_triage_through_real_tools(live: Settings) -> None:
    """Scripted model, real tools: proves the whole loop works against a cluster."""
    async with Client(kubernetes.build_server(live)) as c:
        pods = (await tool(c, "list_pods", namespace="demo"))["result"]
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
        call("kubernetes_list_pods", "c1", namespace="demo"),
        call("kubernetes_pod_logs", "c2", namespace="demo", name=pod, previous=True),
        call("kubernetes_describe_deployment", "c3", namespace="demo", name="checkout"),
        call("TriageReport", "c4", **report),
    )
    root = FastMCP("aiops")
    root.mount(kubernetes.build_server(live), namespace="kubernetes")
    alert = AlertGroup.model_validate(
        {
            "status": "firing",
            "commonLabels": {"alertname": "KubePodCrashLooping", "namespace": "demo"},
            "alerts": [{"status": "firing", "labels": {"pod": pod}}],
        }
    )
    async with agent.open_agent(live, model, mcp=root) as a:
        outcome = await agent.start(a, alert, "it-1")
    assert outcome.report is not None and outcome.report.category == "bad_rollout"
    assert len(outcome.tool_calls) == 4


async def test_record_eval_fixtures(live: Settings) -> None:
    """With AIOPS_RECORD_DIR set, save real tool outputs for the eval scenarios."""
    out = os.environ.get("AIOPS_RECORD_DIR")
    if not out:
        pytest.skip("AIOPS_RECORD_DIR not set")
    import json
    from pathlib import Path

    rec: dict[str, Any] = {}
    async with Client(kubernetes.build_server(live)) as c:
        pods = (await tool(c, "list_pods", namespace="demo"))["result"]
        rec["kubernetes_list_pods"] = pods
        rec["kubernetes_list_deployments"] = await tool(c, "list_deployments", namespace="demo")
        rec["kubernetes_get_events"] = await tool(c, "get_events", namespace="demo")
        for name in ("checkout", "reports", "frontend"):
            rec[f"deploy:{name}"] = await tool(
                c, "describe_deployment", namespace="demo", name=name
            )
        for p in pods:
            rec[f"pod:{p['name']}"] = await tool(
                c, "describe_pod", namespace="demo", name=p["name"]
            )
            for previous in (False, True):
                r = await c.call_tool(
                    "pod_logs",
                    {"namespace": "demo", "name": p["name"], "previous": previous},
                    raise_on_error=False,
                )
                rec[f"logs:{p['name']}:{previous}"] = r.content[0].text
    Path(out).mkdir(parents=True, exist_ok=True)
    data = json.dumps(rec, indent=2, default=str)
    (Path(out) / "recording.json").write_text(data)
