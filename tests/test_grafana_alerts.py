"""Grafana Alerting as a second alert source (slice 4.3d): its webhook contact point,
captured from a real Grafana 13.2 in tests/fixtures, becomes the same Alert group an
Alertmanager sends, behind the same Contract token, dedup and resolve rules."""

import json
from pathlib import Path
from typing import Any

from aiops_agent import agent
from aiops_agent.config import Settings
from aiops_agent.models import GrafanaAlertGroup
from tests.conftest import REPORT, call
from tests.test_api import (  # noqa: F401 - _database: every test here needs Postgres
    AUTH,
    BANK_HOOK,
    EVICT_THEN_REPORT,
    HOOK,
    _database,
    bank,
    client,
    wait_for,
)

FIXTURES = Path(__file__).parent / "fixtures"
FIRING = json.loads((FIXTURES / "grafana-firing.json").read_text())
RESOLVED = json.loads((FIXTURES / "grafana-resolved.json").read_text())
GRAFANA = "/contracts/acme/grafana"


def test_a_grafana_notification_becomes_an_alert_group() -> None:
    group = GrafanaAlertGroup.model_validate(FIRING).normalized()
    stored = group.model_dump(mode="json")
    (alert,) = stored["alerts"]
    assert group.title == "PaymentsChargeErrors"
    assert stored["groupKey"] == "grafana:" + FIRING["groupKey"]
    assert alert["fingerprint"] == FIRING["alerts"][0]["fingerprint"]
    # The one thing Grafana adds, kept where the agent reads it; the rest dropped.
    assert alert["annotations"]["query_values"].startswith(
        "[ var='B' labels={} type='reduce' value=52"
    )
    assert alert["annotations"]["summary"] == "payments charges are failing"
    assert {"values", "valueString", "silenceURL", "ruleUID"}.isdisjoint(alert)
    assert {"title", "message", "state"}.isdisjoint(stored)
    assert "query_values" in agent.alert_prompt(group)


def test_grafana_alerts_take_the_contracts_token_only(
    settings: Settings, fake_cluster: Any
) -> None:
    with client(settings, fake_cluster, more=bank()) as c:
        assert c.post(GRAFANA, json=FIRING).status_code in (401, 403)
        assert c.post(GRAFANA, json=FIRING, headers=AUTH).status_code == 401
        assert c.post(GRAFANA, json=FIRING, headers=BANK_HOOK).status_code == 401
        assert c.post("/contracts/nope/grafana", json=FIRING, headers=HOOK).status_code == 401


def test_a_grafana_alert_is_triaged_once_with_its_query_values(
    settings: Settings, fake_cluster: Any
) -> None:
    with client(settings, fake_cluster, call("TriageReport", "r", **REPORT)) as c:
        first = c.post(GRAFANA, json=FIRING, headers=HOOK).json()
        assert first["status"] == "accepted"
        t = wait_for(c, first["investigation"], "done")
        assert t["title"] == "PaymentsChargeErrors"
        assert "value=52" in t["input"]["alerts"][0]["annotations"]["query_values"]
        again = c.post(GRAFANA, json=FIRING, headers=HOOK).json()  # Grafana's repeat
        assert again == {"status": "duplicate", "investigation": first["investigation"]}


def test_a_resolved_grafana_alert_makes_proposed_actions_stale(
    settings: Settings, fake_cluster: Any
) -> None:
    with client(settings, fake_cluster, *EVICT_THEN_REPORT, actions=True) as c:
        tid = c.post(GRAFANA, json=FIRING, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "awaiting_approval")
        assert c.post(GRAFANA, json=RESOLVED, headers=HOOK).json() == {
            "status": "stale",
            "investigations": [tid],
        }
        wait_for(c, tid, "done")
    fake_cluster[0].create_namespaced_pod_eviction.assert_not_called()


def test_an_alertmanager_group_with_the_same_key_leaves_grafanas_alone(
    settings: Settings, fake_cluster: Any
) -> None:
    """Grafana grouping by alertname sends the key an Alertmanager grouping the same
    way would: one source resolving must not stale the other's pending actions."""
    from tests.test_api import RESOLVED as AM_RESOLVED
    from tests.test_api import URL

    with client(settings, fake_cluster, *EVICT_THEN_REPORT, actions=True) as c:
        tid = c.post(GRAFANA, json=FIRING, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "awaiting_approval")
        same_key = {**AM_RESOLVED, "groupKey": FIRING["groupKey"]}
        assert c.post(URL, json=same_key, headers=HOOK).json()["status"] == "ignored"
        assert c.get(f"/investigations/{tid}", headers=AUTH).json()["status"] == (
            "awaiting_approval"
        )
