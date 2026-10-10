from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from aiops_agent.config import Settings
from aiops_agent.servers import kubernetes


def test_refuses_to_guess_a_cluster() -> None:
    s = Settings(_env_file=None, namespaces=["shop"])  # no context, not in-cluster
    with pytest.raises(RuntimeError, match="Refusing to guess"):
        kubernetes.api_client(s)


def test_refuses_empty_namespace_allowlist(fake_cluster: Any) -> None:
    s = Settings(_env_file=None, kube_context="kind-test")
    with pytest.raises(RuntimeError, match="AIOPS_NAMESPACES"):
        kubernetes.build_server(s, *fake_cluster)


def test_namespaces_parse_from_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIOPS_NAMESPACES", "shop, payments ,")
    assert Settings(_env_file=None).namespaces == ["shop", "payments"]


@pytest.mark.anyio
async def test_namespace_allowlist_is_enforced(settings: Settings, fake_cluster: Any) -> None:
    async with Client(kubernetes.build_server(settings, *fake_cluster)) as c:
        with pytest.raises(ToolError, match="not allowed"):
            await c.call_tool("list_pods", {"namespace": "kube-system"})
    fake_cluster[0].list_namespaced_pod.assert_not_called()


@pytest.mark.anyio
async def test_list_pods_surfaces_crash_and_oom(settings: Settings, fake_cluster: Any) -> None:
    async with Client(kubernetes.build_server(settings, *fake_cluster)) as c:
        pods = (await c.call_tool("list_pods", {"namespace": "shop"})).structured_content
    pod = pods["result"][0]
    assert pod["restarts"] == 7
    assert pod["containers"]["app"]["waiting"] == "CrashLoopBackOff"
    assert pod["last_terminated"]["app"]["terminated"] == "OOMKilled"
    assert pod["last_terminated"]["app"]["exit_code"] == 137


@pytest.mark.anyio
async def test_describe_pod_never_returns_env_values(settings: Settings, fake_cluster: Any) -> None:
    async with Client(kubernetes.build_server(settings, *fake_cluster)) as c:
        result = await c.call_tool(
            "describe_pod", {"namespace": "shop", "name": "checkout-7d9f-abc"}
        )
    text = str(result.structured_content)
    assert "DATABASE_URL" in text and "secret/checkout-creds" in text
    assert "supersecret" not in text
    assert "BackOff" in text  # pod events included


@pytest.mark.anyio
async def test_pod_logs_are_redacted_and_bounded(settings: Settings, fake_cluster: Any) -> None:
    fake_cluster[0].read_namespaced_pod_log.return_value += "x" * 20_000
    async with Client(kubernetes.build_server(settings, *fake_cluster)) as c:
        result = await c.call_tool("pod_logs", {"namespace": "shop", "name": "p", "previous": True})
    text = result.content[0].text
    assert "abcdefghijklmnop" not in text
    assert len(text) < settings.tool_output_limit + 100
    _, kwargs = fake_cluster[0].read_namespaced_pod_log.call_args
    assert kwargs["previous"] is True


@pytest.mark.anyio
async def test_write_tools_absent_unless_enabled(settings: Settings, fake_cluster: Any) -> None:
    async with Client(kubernetes.build_server(settings, *fake_cluster)) as c:
        names = {t.name for t in await c.list_tools()}
    assert "list_pods" in names
    assert not names & {"restart_deployment", "scale_deployment"}


@pytest.mark.anyio
async def test_write_tools_marked_destructive_and_bounded(
    settings: Settings, fake_cluster: Any
) -> None:
    settings.enable_actions = True
    async with Client(kubernetes.build_server(settings, *fake_cluster)) as c:
        tools = {t.name: t for t in await c.list_tools()}
        assert tools["scale_deployment"].annotations.destructive_hint is True
        assert tools["list_pods"].annotations.read_only_hint is True
        with pytest.raises(ToolError, match="between 0 and 10"):
            await c.call_tool(
                "scale_deployment", {"namespace": "shop", "name": "checkout", "replicas": 500}
            )
        await c.call_tool("restart_deployment", {"namespace": "shop", "name": "checkout"})
    patch = fake_cluster[1].patch_namespaced_deployment.call_args.args[2]
    assert "kubectl.kubernetes.io/restartedAt" in str(patch)
