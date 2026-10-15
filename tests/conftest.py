"""Shared fixtures: a fake cluster built from real kubernetes client models, and a
scripted chat model, so the agent runs end-to-end without a cluster or an LLM."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from kubernetes import client as k
from langchain.messages import AIMessage, ToolCall
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

from aiops_agent import contracts
from aiops_agent.config import Settings

NOW = datetime.now(UTC)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


DEMO_CONTRACTS = Path(__file__).parent.parent / "demo" / "contracts"


def use_age_keys(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *contract_ids: str) -> None:
    """Give sops only these demo Contracts' test keys."""
    keys = tmp_path / "keys.txt"
    keys.write_text(
        "".join((DEMO_CONTRACTS / "test-keys" / f"{c}.agekey").read_text() for c in contract_ids)
    )
    monkeypatch.delenv("SOPS_AGE_KEY", raising=False)
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(keys))


@pytest.fixture
def two_contracts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, contracts.Contract]:
    """The two synthetic demo Contracts, for isolation tests: A's data must never reach B."""
    use_age_keys(monkeypatch, tmp_path, "demo-shop", "demo-bank")
    return contracts.load(DEMO_CONTRACTS)


@pytest.fixture
def settings(tmp_path: Any) -> Settings:
    return Settings(
        _env_file=None,
        kube_context="kind-test",
        namespaces=["shop"],
        runbooks_dir=tmp_path / "none",
        model="fake",
    )


def crashlooping_pod() -> k.V1Pod:
    return k.V1Pod(
        metadata=k.V1ObjectMeta(
            name="checkout-7d9f-abc",
            namespace="shop",
            creation_timestamp=NOW - timedelta(hours=1),
            owner_references=[
                k.V1OwnerReference(
                    api_version="apps/v1", kind="ReplicaSet", name="checkout-7d9f", uid="rs1"
                )
            ],
        ),
        spec=k.V1PodSpec(
            node_name="node-1",
            containers=[
                k.V1Container(
                    name="app",
                    image="shop/checkout:1.4.0",
                    env=[k.V1EnvVar(name="DATABASE_URL", value="postgres://u:supersecret@db/shop")],
                    env_from=[
                        k.V1EnvFromSource(secret_ref=k.V1SecretEnvSource(name="checkout-creds"))
                    ],
                    resources=k.V1ResourceRequirements(limits={"memory": "64Mi"}),
                )
            ],
        ),
        status=k.V1PodStatus(
            phase="Running",
            container_statuses=[
                k.V1ContainerStatus(
                    name="app",
                    image="shop/checkout:1.4.0",
                    image_id="",
                    ready=False,
                    restart_count=7,
                    state=k.V1ContainerState(
                        waiting=k.V1ContainerStateWaiting(reason="CrashLoopBackOff")
                    ),
                    last_state=k.V1ContainerState(
                        terminated=k.V1ContainerStateTerminated(
                            reason="OOMKilled",
                            exit_code=137,
                            finished_at=NOW - timedelta(minutes=2),
                        )
                    ),
                )
            ],
        ),
    )


def deployment() -> k.V1Deployment:
    return k.V1Deployment(
        metadata=k.V1ObjectMeta(name="checkout", namespace="shop", uid="dep1"),
        spec=k.V1DeploymentSpec(
            replicas=2,
            selector=k.V1LabelSelector(match_labels={"app": "checkout"}),
            template=k.V1PodTemplateSpec(
                spec=k.V1PodSpec(
                    containers=[k.V1Container(name="app", image="shop/checkout:1.4.0")]
                )
            ),
        ),
        status=k.V1DeploymentStatus(
            ready_replicas=0,
            updated_replicas=2,
            conditions=[
                k.V1DeploymentCondition(
                    type="Available", status="False", reason="MinimumReplicasUnavailable"
                )
            ],
        ),
    )


@pytest.fixture
def fake_cluster() -> tuple[MagicMock, MagicMock]:
    core, apps = MagicMock(), MagicMock()
    core.list_namespaced_pod.return_value = k.V1PodList(items=[crashlooping_pod()])
    core.read_namespaced_pod.return_value = crashlooping_pod()
    core.list_namespaced_event.return_value = k.CoreV1EventList(
        items=[
            k.CoreV1Event(
                metadata=k.V1ObjectMeta(name="e1", creation_timestamp=NOW),
                involved_object=k.V1ObjectReference(kind="Pod", name="checkout-7d9f-abc"),
                type="Warning",
                reason="BackOff",
                message="Back-off restarting failed container",
                count=7,
                last_timestamp=NOW,
            )
        ]
    )
    core.read_namespaced_pod_log.return_value = (
        "starting checkout\nAuthorization: Bearer abcdefghijklmnopqrstuvwxyz123456\n"
        "java.lang.OutOfMemoryError: Java heap space\n"
    )
    apps.list_namespaced_deployment.return_value = k.V1DeploymentList(items=[deployment()])
    apps.read_namespaced_deployment.return_value = deployment()
    apps.list_namespaced_replica_set.return_value = k.V1ReplicaSetList(items=[])
    return core, apps


class ScriptedModel(GenericFakeChatModel):
    """Replays a fixed list of AI messages; tool binding is a no-op."""

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedModel":
        return self


def scripted(*steps: AIMessage) -> ScriptedModel:
    return ScriptedModel(messages=iter(steps))


def call(tool: str, call_id: str, /, **args: Any) -> AIMessage:
    return AIMessage(content="", tool_calls=[ToolCall(name=tool, args=args, id=call_id)])


REPORT = {
    "summary": "checkout is crash looping: the JVM runs out of memory under a 64Mi limit.",
    "category": "resource_limits",
    "probable_root_cause": "Memory limit 64Mi is below the JVM heap requirement.",
    "confidence": "high",
    "severity": "high",
    "affected": ["shop/deployment/checkout"],
    "evidence": [
        {"source": "kubernetes_pod_logs", "finding": "java.lang.OutOfMemoryError: Java heap space"}
    ],
    "recommended_actions": ["Raise the memory limit to 512Mi", "Set -XX:MaxRAMPercentage=75"],
}
