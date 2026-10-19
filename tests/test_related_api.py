"""Related alert groups at the Hub's door: joining an open Triage, its thread post,
re-sends, the window, and what never joins (CONTEXT.md)."""

from typing import Any

import pytest
from pydantic import SecretStr

from aiops_agent import api
from aiops_agent.config import Settings
from tests.conftest import REPORT, call
from tests.test_api import AUTH, BANK_HOOK, BANK_URL, EVICT_THEN_REPORT, HOOK, URL, bank, client
from tests.test_console import OPERATOR, VIEW
from tests.test_restart import wait_for
from tests.test_slack import ACME, TOKEN, FakeSlack

DONE = [call("TriageReport", "c1", **REPORT)]


def alert(key: str, name: str, severity: str = "warning", status: str = "firing") -> dict[str, Any]:
    labels = {"alertname": name, "namespace": "shop", "service": "payments", "severity": severity}
    return {
        "status": status,
        "groupKey": key,
        "commonLabels": labels,
        "alerts": [{"status": status, "labels": labels, "fingerprint": f"{key}-1"}],
    }


ERRORS, LATENCY = alert("g-errors", "PaymentsErrors"), alert("g-latency", "PaymentsLatency")


@pytest.fixture(autouse=True)
def _db(settings: Settings, database_url: str) -> None:
    settings.database_url = SecretStr(database_url)


def test_a_related_group_joins_the_open_triage_and_says_so_in_its_thread(
    settings: Settings, fake_cluster: Any
) -> None:
    settings.slack_bot_token = SecretStr(TOKEN)
    settings.console_operators = {OPERATOR}
    slack = FakeSlack()
    with client(settings, fake_cluster, *DONE, slack=slack.transport(), acme_channel=ACME) as c:
        tid = c.post(URL, json=ERRORS, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        slack.until(3)
        louder = alert("g-latency", "PaymentsLatency", severity="critical")
        r = c.post(URL, json=louder, headers=HOOK).json()
        assert r == {"status": "related", "investigation": tid}
        assert [t["id"] for t in c.get("/investigations", headers=AUTH).json()] == [tid]
        slack.until(4)
        method, payload, _ = slack.calls[-1]
        parent_ts = "1700000000.000001"  # the Triage's first post: its thread
        assert (method, payload["channel"], payload["thread_ts"]) == (
            "chat.postMessage",
            ACME,
            parent_ts,
        )
        assert "Related alert group joined this Triage: *PaymentsLatency shop*" in payload["text"]
        assert "service=payments" in payload["text"] and "(critical) is higher" in payload["text"]
        # A re-send with nothing new is a duplicate of the Triage it joined.
        again = c.post(URL, json=louder, headers=HOOK).json()
        assert again == {"status": "duplicate", "investigation": tid}
        page = c.get(f"/console/investigations/{tid}", headers=VIEW).text
        assert "Related alert groups" in page and "PaymentsLatency shop" in page
        assert "<code>service=payments</code>" in page and "higher severity" in page


def test_outside_the_window_or_once_resolved_or_failed_a_group_starts_its_own(
    settings: Settings, fake_cluster: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with client(settings, fake_cluster, *DONE, *DONE) as c:
        tid = c.post(URL, json=ERRORS, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        later = api.now() + 31 * 60
        monkeypatch.setattr(api, "now", lambda: later)
        r = c.post(URL, json=LATENCY, headers=HOOK).json()
        assert r["status"] == "accepted" and r["investigation"] != tid


def test_a_resolved_triage_is_not_open(settings: Settings, fake_cluster: Any) -> None:
    with client(settings, fake_cluster, *DONE, *DONE) as c:
        tid = c.post(URL, json=ERRORS, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        c.post(URL, json=alert("g-errors", "PaymentsErrors", status="resolved"), headers=HOOK)
        assert c.post(URL, json=LATENCY, headers=HOOK).json()["status"] == "accepted"


def test_a_failed_triage_is_not_open(settings: Settings, fake_cluster: Any) -> None:
    with client(settings, fake_cluster) as c:  # no model steps: the Run fails
        tid = c.post(URL, json=ERRORS, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "failed")
        assert c.post(URL, json=LATENCY, headers=HOOK).json()["status"] == "accepted"


def test_a_related_group_resolving_never_makes_the_triages_actions_stale(
    settings: Settings, fake_cluster: Any
) -> None:
    errors = {**ERRORS, "alerts": [{**ERRORS["alerts"][0], "labels": {"pod": "checkout-7d9f-abc"}}]}
    with client(settings, fake_cluster, *EVICT_THEN_REPORT, actions=True) as c:
        tid = c.post(URL, json=errors, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "awaiting_approval")
        assert c.post(URL, json=LATENCY, headers=HOOK).json()["status"] == "related"
        resolved = alert("g-latency", "PaymentsLatency", status="resolved")
        assert c.post(URL, json=resolved, headers=HOOK).json()["status"] == "ignored"
        assert wait_for(c, tid, "awaiting_approval")["pending"]


def test_switched_off_with_no_match_labels(settings: Settings, fake_cluster: Any) -> None:
    off = {"related": {"match_labels": []}}
    with client(settings, fake_cluster, *DONE, *DONE, acme=off) as c:
        tid = c.post(URL, json=ERRORS, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        assert c.post(URL, json=LATENCY, headers=HOOK).json()["status"] == "accepted"


def test_another_contracts_triage_is_never_joined(settings: Settings, fake_cluster: Any) -> None:
    """Identical labels, same physical cluster: still a Triage of its own."""
    with client(settings, fake_cluster, *DONE, *DONE, more=bank()) as c:
        tid = c.post(URL, json=ERRORS, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        r = c.post(BANK_URL, json=LATENCY, headers=BANK_HOOK).json()
        assert r["status"] == "accepted" and r["investigation"] != tid


def test_a_contracts_own_window_overrides_the_hubs(
    settings: Settings, fake_cluster: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with client(settings, fake_cluster, *DONE, acme={"related": {"window_minutes": 60}}) as c:
        tid = c.post(URL, json=ERRORS, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        later = api.now() + 31 * 60
        monkeypatch.setattr(api, "now", lambda: later)
        assert c.post(URL, json=LATENCY, headers=HOOK).json() == {
            "status": "related",
            "investigation": tid,
        }


@pytest.mark.anyio
async def test_only_triages_are_open(database_url: str) -> None:
    """A Question has no Alert group to compare: never a candidate."""
    from aiops_agent.models import Investigation
    from aiops_agent.store import Store, connect

    async with connect(database_url) as pool:
        store = Store(pool)
        await store.migrate()
        triage = Investigation(
            id="t", contract_id="acme", title="t", started=api.now(), input=ERRORS
        )
        question = triage.model_copy(
            update={"id": "q", "kind": "question", "input": {"question": "?"}}
        )
        await store.insert(triage)
        await store.insert(question)
        assert [t.id for t in await store.open_triages("acme", api.now() - 60)] == ["t"]
