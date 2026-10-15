import os
from typing import Any

import pytest
import yaml
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from pydantic import SecretStr

from aiops_agent import contracts
from aiops_agent.config import Settings
from aiops_agent.servers import kubernetes
from tests.conftest import EXEC_USER, kubeconfig, make_contract


def k8s(settings: Settings, fake_cluster: Any, actions: bool = False, **contract: Any) -> FastMCP:
    c = make_contract(enable_actions=actions, **contract)
    apis = {cl.name: fake_cluster for cl in c.clusters}
    k = c.integrations[0]
    assert isinstance(k, contracts.Kubernetes)
    return kubernetes.build_server(c, k, settings.tool_output_limit, apis)


def test_env_settings_refuse_to_guess_a_cluster() -> None:
    s = Settings(_env_file=None, namespaces=["shop"])  # no context, not in-cluster
    with pytest.raises(RuntimeError, match="context is required unless in_cluster"):
        contracts.from_settings(s)


def test_env_settings_refuse_empty_namespace_allowlist() -> None:
    s = Settings(_env_file=None, kube_context="kind-test")
    with pytest.raises(RuntimeError, match=r"clusters\.0\.namespaces.*AIOPS_NAMESPACES"):
        contracts.from_settings(s)


def test_env_settings_become_one_contract_without_sops(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(contracts, "_decrypt", lambda _: pytest.fail("sops must not run"))
    s = Settings(
        _env_file=None,
        kube_context="kind-test",
        namespaces=["shop"],
        enable_actions=True,
        prometheus_url="http://prom",
        prometheus_token=SecretStr("tok"),
    )
    c = contracts.from_settings(s)
    assert [i.name for i in c.integrations] == ["kubernetes", "prometheus", "runbooks"]
    assert c.secret("prometheus-token").get_secret_value() == "tok"
    assert c.runbook_dirs == [s.runbooks_dir]


def test_kubeconfig_secret_is_parsed_in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        kubernetes.config,
        "new_client_from_config_dict",
        lambda d, context: seen.update(d=d, ctx=context),
    )
    monkeypatch.setattr(
        kubernetes.config, "new_client_from_config", lambda **_: pytest.fail("file")
    )
    data = {
        "id": "acme",
        "name": "Acme",
        "clusters": [
            {"name": "prod", "context": "p", "namespaces": ["shop"], "kubeconfig_secret": "kc"}
        ],
        "integrations": [{"name": "kubernetes"}],
    }
    c = contracts.build(data, secrets={"kc": SecretStr("apiVersion: v1\nkind: Config\n")})
    kubernetes.api_client(c.clusters[0], c)
    assert seen == {"d": {"apiVersion": "v1", "kind": "Config"}, "ctx": "p"}


@pytest.mark.anyio
async def test_an_only_cluster_is_named_outright(settings: Settings, fake_cluster: Any) -> None:
    """The alert's label may name it differently: no hunting for a match."""
    async with Client(k8s(settings, fake_cluster)) as c:
        tools = {t.name: t for t in await c.list_tools()}
    cluster = tools["list_pods"].input_schema["properties"]["cluster"]
    assert cluster["description"] == "This Contract's only cluster: always pass 'test'."


@pytest.mark.anyio
async def test_cluster_and_namespace_are_checked_together(
    settings: Settings, fake_cluster: Any
) -> None:
    server = k8s(settings, fake_cluster, clusters={"prod": ["shop"], "stg": ["shop-stg"]})
    async with Client(server) as c:
        tools = {t.name: t for t in await c.list_tools()}
        cluster = tools["list_pods"].input_schema["properties"]["cluster"]
        assert cluster["enum"] == ["prod", "stg"]
        assert "use the alert's cluster label" in cluster["description"]
        await c.call_tool("list_pods", {"cluster": "prod", "namespace": "shop"})
        with pytest.raises(ToolError, match="'shop' is not allowed in cluster 'stg'"):
            await c.call_tool("list_pods", {"cluster": "stg", "namespace": "shop"})
        with pytest.raises(
            ToolError, match=r"not one of this Contract's clusters: \['prod', 'stg'\]"
        ):
            await c.call_tool("list_pods", {"cluster": "bank-kind", "namespace": "shop"})
    assert fake_cluster[0].list_namespaced_pod.call_count == 1


def test_namespaces_parse_from_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIOPS_NAMESPACES", "shop, payments ,")
    assert Settings(_env_file=None).namespaces == ["shop", "payments"]


@pytest.mark.anyio
async def test_namespace_allowlist_is_enforced(settings: Settings, fake_cluster: Any) -> None:
    async with Client(k8s(settings, fake_cluster)) as c:
        with pytest.raises(ToolError, match="not allowed"):
            await c.call_tool("list_pods", {"cluster": "test", "namespace": "kube-system"})
    fake_cluster[0].list_namespaced_pod.assert_not_called()


@pytest.mark.anyio
async def test_list_pods_surfaces_crash_and_oom(settings: Settings, fake_cluster: Any) -> None:
    async with Client(k8s(settings, fake_cluster)) as c:
        pods = (
            await c.call_tool("list_pods", {"cluster": "test", "namespace": "shop"})
        ).structured_content
    pod = pods["result"][0]
    assert pod["restarts"] == 7
    assert pod["containers"]["app"]["waiting"] == "CrashLoopBackOff"
    assert pod["last_terminated"]["app"]["terminated"] == "OOMKilled"
    assert pod["last_terminated"]["app"]["exit_code"] == 137


@pytest.mark.anyio
async def test_describe_pod_never_returns_env_values(settings: Settings, fake_cluster: Any) -> None:
    async with Client(k8s(settings, fake_cluster)) as c:
        result = await c.call_tool(
            "describe_pod", {"cluster": "test", "namespace": "shop", "name": "checkout-7d9f-abc"}
        )
    text = str(result.structured_content)
    assert "DATABASE_URL" in text and "secret/checkout-creds" in text
    assert "supersecret" not in text
    assert "BackOff" in text  # pod events included


@pytest.mark.anyio
async def test_pod_logs_are_redacted_and_bounded(settings: Settings, fake_cluster: Any) -> None:
    fake_cluster[0].read_namespaced_pod_log.return_value += "x" * 20_000
    async with Client(k8s(settings, fake_cluster)) as c:
        result = await c.call_tool(
            "pod_logs", {"cluster": "test", "namespace": "shop", "name": "p", "previous": True}
        )
    text = result.content[0].text
    assert "abcdefghijklmnop" not in text
    assert len(text) < settings.tool_output_limit + 100
    _, kwargs = fake_cluster[0].read_namespaced_pod_log.call_args
    assert kwargs["previous"] is True


@pytest.mark.anyio
async def test_write_tools_absent_unless_enabled(settings: Settings, fake_cluster: Any) -> None:
    async with Client(k8s(settings, fake_cluster)) as c:
        names = {t.name for t in await c.list_tools()}
    assert "list_pods" in names
    assert not names & {"evict_pod", "scale_deployment"}


@pytest.mark.anyio
async def test_write_tools_marked_destructive_and_bounded(
    settings: Settings, fake_cluster: Any
) -> None:
    async with Client(k8s(settings, fake_cluster, actions=True)) as c:
        tools = {t.name: t for t in await c.list_tools()}
        assert tools["scale_deployment"].annotations.destructive_hint is True
        assert tools["list_pods"].annotations.read_only_hint is True
        with pytest.raises(ToolError, match="between 0 and 10"):
            await c.call_tool(
                "scale_deployment",
                {"cluster": "test", "namespace": "shop", "name": "checkout", "replicas": 500},
            )
        await c.call_tool(
            "evict_pod", {"cluster": "test", "namespace": "shop", "name": "checkout-7d9f-abc"}
        )
    fake_cluster[0].create_namespaced_pod_eviction.assert_called_once()


@pytest.mark.anyio
async def test_evict_refuses_bare_pods_and_reports_pdb(
    settings: Settings, fake_cluster: Any
) -> None:
    from kubernetes.client.exceptions import ApiException

    core = fake_cluster[0]
    async with Client(k8s(settings, fake_cluster, actions=True)) as c:
        core.create_namespaced_pod_eviction.side_effect = ApiException(status=429)
        with pytest.raises(ToolError, match="PodDisruptionBudget"):
            await c.call_tool(
                "evict_pod", {"cluster": "test", "namespace": "shop", "name": "checkout-7d9f-abc"}
            )
        core.read_namespaced_pod.return_value.metadata.owner_references = None
        with pytest.raises(ToolError, match="no controller"):
            await c.call_tool(
                "evict_pod", {"cluster": "test", "namespace": "shop", "name": "checkout-7d9f-abc"}
            )


@pytest.mark.anyio
async def test_pod_logs_retries_restart_race(
    settings: Settings, fake_cluster: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(kubernetes, "LOG_RETRY_SECONDS", 0)
    core = fake_cluster[0]
    core.read_namespaced_pod_log.side_effect = [
        "unable to retrieve container logs for containerd://abc",
        "FATAL: DATABASE_URL is not set",
    ]
    async with Client(k8s(settings, fake_cluster)) as c:
        result = await c.call_tool(
            "pod_logs", {"cluster": "test", "namespace": "shop", "name": "p", "previous": True}
        )
        assert "DATABASE_URL" in result.content[0].text
        # previous gone for good (GC'd while in CrashLoopBackOff): fall back to current
        gone = "unable to retrieve container logs for x"
        core.read_namespaced_pod_log.side_effect = [gone, gone, gone, "FATAL: boom"]
        result = await c.call_tool(
            "pod_logs", {"cluster": "test", "namespace": "shop", "name": "p", "previous": True}
        )
        assert "FATAL: boom" in result.content[0].text
        assert "previous instance's logs are gone" in result.content[0].text
        core.read_namespaced_pod_log.side_effect = None
        core.read_namespaced_pod_log.return_value = gone
        with pytest.raises(ToolError, match="being replaced"):
            await c.call_tool("pod_logs", {"cluster": "test", "namespace": "shop", "name": "p"})


@pytest.mark.anyio
async def test_rollout_history_shows_config_diff(settings: Settings, fake_cluster: Any) -> None:
    from kubernetes import client as k

    def rs(rev: str, env: list[str]) -> Any:
        return k.V1ReplicaSet(
            metadata=k.V1ObjectMeta(
                name=f"checkout-{rev}",
                annotations={"deployment.kubernetes.io/revision": rev},
                owner_references=[
                    k.V1OwnerReference(
                        api_version="apps/v1", kind="Deployment", name="checkout", uid="dep1"
                    )
                ],
            ),
            spec=k.V1ReplicaSetSpec(
                selector=k.V1LabelSelector(),
                template=k.V1PodTemplateSpec(
                    spec=k.V1PodSpec(
                        containers=[
                            k.V1Container(
                                name="app",
                                image="shop/checkout:1.4.0",
                                env=[k.V1EnvVar(name=n, value="secret-value") for n in env],
                            )
                        ]
                    )
                ),
            ),
            status=k.V1ReplicaSetStatus(replicas=1),
        )

    fake_cluster[1].list_namespaced_replica_set.return_value = k.V1ReplicaSetList(
        items=[rs("1", ["DATABASE_URL"]), rs("2", [])]
    )
    async with Client(k8s(settings, fake_cluster)) as c:
        out = (
            await c.call_tool(
                "describe_deployment", {"cluster": "test", "namespace": "shop", "name": "checkout"}
            )
        ).structured_content
    history = {h["revision"]: h["config"]["app"]["env"] for h in out["rollout_history"]}
    assert history == {"2": [], "1": ["DATABASE_URL"]}
    assert "secret-value" not in str(out)


def plugin_cluster(**cluster: Any) -> contracts.Contract:
    data = {
        "id": "acme",
        "name": "Acme",
        "clusters": [{"name": "prod", "context": "p", "namespaces": ["shop"], **cluster}],
        "integrations": [{"name": "kubernetes"}],
    }
    kc = SecretStr(yaml.safe_dump(kubeconfig(EXEC_USER)))
    return contracts.build(data, secrets={"kc": kc})


def test_plugin_in_a_kubeconfig_secret_never_reaches_the_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded: list[Any] = []
    monkeypatch.setattr(
        kubernetes.config, "new_client_from_config_dict", lambda d, context: loaded.append(d)
    )
    c = plugin_cluster(kubeconfig_secret="kc")
    with pytest.raises(RuntimeError, match=r"Contract 'acme', cluster 'prod'.*exec plugin 'aws'"):
        kubernetes.api_client(c.clusters[0], c)
    assert loaded == []
    c = plugin_cluster(kubeconfig_secret="kc", allow_exec=True)
    kubernetes.api_client(c.clusters[0], c)
    assert len(loaded) == 1


@pytest.mark.parametrize("plugin_first", [True, False])
def test_default_kubeconfig_is_checked_as_kubectl_merges_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, plugin_first: bool
) -> None:
    """KUBECONFIG lists files; the first to define a user wins, as in kubectl."""
    plugin, token = tmp_path / "plugin.yaml", tmp_path / "token.yaml"
    plugin.write_text(yaml.safe_dump(kubeconfig(EXEC_USER)))
    token.write_text(yaml.safe_dump(kubeconfig({"token": "t"})))
    order = [plugin, token] if plugin_first else [token, plugin]
    monkeypatch.setenv("KUBECONFIG", os.pathsep.join(map(str, order)))
    loaded: list[Any] = []
    monkeypatch.setattr(kubernetes.config, "new_client_from_config", lambda **kw: loaded.append(kw))
    c = plugin_cluster()
    if plugin_first:
        with pytest.raises(RuntimeError, match="exec plugin 'aws'"):
            kubernetes.api_client(c.clusters[0], c)
        assert loaded == []
    else:
        kubernetes.api_client(c.clusters[0], c)
        assert loaded == [{"config_file": None, "context": "p"}]
