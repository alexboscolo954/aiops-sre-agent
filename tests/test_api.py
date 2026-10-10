import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from fastmcp import FastMCP
from pydantic import SecretStr

from aiops_agent.api import create_app
from aiops_agent.config import Settings
from aiops_agent.servers import kubernetes
from tests.conftest import REPORT, call, scripted

AUTH = {"Authorization": "Bearer test-token"}
ALERT = {
    "status": "firing",
    "groupKey": "g1",
    "commonLabels": {"alertname": "KubePodCrashLooping", "namespace": "shop"},
    "alerts": [{"status": "firing", "labels": {"pod": "checkout-7d9f-abc"}, "fingerprint": "f1"}],
}


def client(settings: Settings, fake_cluster: Any, *steps: Any) -> TestClient:
    settings.api_token = SecretStr("test-token")

    def mcp() -> FastMCP:
        root = FastMCP("aiops")
        root.mount(kubernetes.build_server(settings, *fake_cluster), namespace="kubernetes")
        return root

    return TestClient(create_app(settings, scripted(*steps), mcp))


def wait_for(c: TestClient, triage_id: str, status: str) -> dict[str, Any]:
    for _ in range(100):
        t: dict[str, Any] = c.get(f"/triages/{triage_id}", headers=AUTH).json()
        if t["status"] == status:
            return t
        time.sleep(0.02)
    raise AssertionError(f"triage stuck in {t['status']}: {t}")


def test_refuses_to_start_without_token(settings: Settings) -> None:
    with pytest.raises(RuntimeError, match="AIOPS_API_TOKEN"):
        create_app(settings, scripted())


def test_webhook_requires_auth(settings: Settings, fake_cluster: Any) -> None:
    with client(settings, fake_cluster) as c:
        assert c.post("/alertmanager", json=ALERT).status_code in {401, 403}
        bad = {"Authorization": "Bearer nope"}
        assert c.post("/alertmanager", json=ALERT, headers=bad).status_code == 401
        assert c.get("/healthz").status_code == 200


def test_alert_to_report_and_dedup(settings: Settings, fake_cluster: Any) -> None:
    steps = [
        call("kubernetes_list_pods", "c1", namespace="shop"),
        call("TriageReport", "c2", **REPORT),
    ]
    with client(settings, fake_cluster, *steps) as c:
        r = c.post("/alertmanager", json=ALERT, headers=AUTH).json()
        assert r["status"] == "accepted"
        t = wait_for(c, r["triage"], "done")
        assert t["report"]["category"] == "oom_killed"
        again = c.post("/alertmanager", json=ALERT, headers=AUTH).json()
        assert again == {"status": "duplicate", "triage": r["triage"]}
        assert "aiops_tool_calls_total" in c.get("/metrics").text


def test_resolved_alerts_are_ignored(settings: Settings, fake_cluster: Any) -> None:
    with client(settings, fake_cluster) as c:
        resolved = {
            **ALERT,
            "status": "resolved",
            "alerts": [{**ALERT["alerts"][0], "status": "resolved"}],
        }
        assert c.post("/alertmanager", json=resolved, headers=AUTH).json()["status"] == "ignored"


def test_approval_flow_over_http(settings: Settings, fake_cluster: Any) -> None:
    settings.enable_actions = True
    steps = [
        call("kubernetes_restart_deployment", "c1", namespace="shop", name="checkout"),
        call("TriageReport", "c2", **REPORT),
    ]
    with client(settings, fake_cluster, *steps) as c:
        tid = c.post("/alertmanager", json=ALERT, headers=AUTH).json()["triage"]
        t = wait_for(c, tid, "awaiting_approval")
        assert t["pending"][0]["name"] == "kubernetes_restart_deployment"
        fake_cluster[1].patch_namespaced_deployment.assert_not_called()

        r = c.post(f"/triages/{tid}/decision", json={"approve": False}, headers=AUTH)
        assert r.status_code == 202
        wait_for(c, tid, "done")
        fake_cluster[1].patch_namespaced_deployment.assert_not_called()
        again = c.post(f"/triages/{tid}/decision", json={"approve": True}, headers=AUTH)
        assert again.status_code == 409
