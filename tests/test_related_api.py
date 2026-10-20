"""Related alert groups at the Hub's door: joining an open Triage, its thread post,
re-sends, the window, what never joins (CONTEXT.md), and the Operator's Triage
separately button."""

# ruff: noqa: F811 - sock is test_slack's fixture, imported for these tests
import json
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from aiops_agent import api
from aiops_agent.config import Settings
from tests.conftest import REPORT, call
from tests.test_api import AUTH, BANK_HOOK, BANK_URL, EVICT_THEN_REPORT, HOOK, URL, bank, client
from tests.test_console import OPERATOR, VIEW
from tests.test_cost import EVICT, HAIKU, used
from tests.test_restart import wait_for
from tests.test_slack import (
    ACME,
    TOKEN,
    FakeSlack,
    FakeSocket,
    click,
    ephemerals,
    replies,
    sock,  # noqa: F401
    until,
)
from tests.test_slack import OPERATOR as CLICKER  # the Slack Operator, a member id

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
        assert "blocks" not in payload  # no Socket Mode, no button
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
        assert [t.id for t in await store.open_triages("acme", api.now() - 60, "g")] == ["t"]


# Triage separately: the Operator's button on the related group's post.

GONE = "Already triaged separately, or not a related group of this Triage."


@pytest.fixture
def buttons(settings: Settings, sock: FakeSocket) -> FakeSocket:
    """Socket Mode on: the bot token, the app token and the Operator."""
    settings.slack_bot_token = SecretStr(TOKEN)
    return sock


def with_fingerprint(group: dict[str, Any], fingerprint: str) -> dict[str, Any]:
    return {**group, "alerts": [{**group["alerts"][0], "fingerprint": fingerprint}]}


def related_post(slack: FakeSlack) -> tuple[str, str]:
    """The related group's post: its ts (FakeSlack numbers every call) and the
    Triage separately button's value."""
    for i, (_, payload, _) in enumerate(slack.calls):
        for block in payload.get("blocks", []):
            for e in block.get("elements", []):
                if e.get("action_id") == "triage_separately":
                    return f"1700000000.{i + 1:06d}", e["value"]
    raise AssertionError("no Triage separately button")


def has_button(slack: FakeSlack) -> bool:
    try:
        return bool(related_post(slack))
    except AssertionError:
        return False


def ids(c: TestClient) -> list[str]:
    return [t["id"] for t in c.get("/investigations", headers=AUTH).json()]


def triage_rows(database_url: str) -> int:
    with psycopg.connect(database_url) as conn:
        row = conn.execute("select count(*) from investigations").fetchone()
        return int(row[0]) if row else 0


def separate(c: TestClient, slack: FakeSlack, sock: FakeSocket, steps_done: bool = True) -> str:
    """ERRORS' Triage, LATENCY joins it, the Operator clicks: LATENCY's own Triage."""
    a = c.post(URL, json=ERRORS, headers=HOOK).json()["investigation"]
    wait_for(c, a, "done" if steps_done else "awaiting_approval")
    assert c.post(URL, json=LATENCY, headers=HOOK).json() == {
        "status": "related",
        "investigation": a,
    }
    until(lambda: has_button(slack))
    ts, value = related_post(slack)
    assert json.loads(value) == {"id": a, "related": json.loads(value)["related"]}
    sock.send(click("triage_separately", value, message_ts=ts))
    until(lambda: len(ids(c)) == 2)
    return a


def test_the_operator_has_a_related_group_triaged_separately_once(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    settings.console_operators = {OPERATOR}
    sock = buttons
    slack = FakeSlack(sock.url)
    with client(
        settings, fake_cluster, *DONE, *DONE, slack=slack.transport(), acme_channel=ACME
    ) as c:
        a = separate(c, slack, sock)
        ts, value = related_post(slack)
        sock.send(click("triage_separately", value, message_ts=ts))  # a second click
        (b,) = set(ids(c)) - {a}
        t = wait_for(c, b, "done")
        assert (t["group_key"], t["title"]) == ("g-latency", "PaymentsLatency shop")
        until(lambda: ephemerals(slack) == [(CLICKER, GONE)])
        reply = "<@U0OPERATOR1> had *PaymentsLatency shop* triaged separately, in a new thread."
        until(lambda: any(reply in r for r in replies(slack)))
        # The post clicked keeps its text and loses its button.
        (update,) = [p for m, p, _ in slack.calls if m == "chat.update" and p["ts"] == ts]
        assert update["blocks"] == [] and "service=payments" in update["text"]
        assert update["text"].endswith(":mag: Triaged separately.")
        # Its own thread: a new parent post, not a reply in the Triage it joined.
        parents = [p for m, p, _ in slack.calls if m == "chat.postMessage" and "thread_ts" not in p]
        assert [p["text"].count("PaymentsLatency") for p in parents] == [0, 1]
        # From now on its re-sends are duplicates of its own Triage.
        again = c.post(URL, json=LATENCY, headers=HOOK).json()
        assert again == {"status": "duplicate", "investigation": b}
        page = c.get(f"/console/investigations/{a}", headers=VIEW).text
        assert f'<a href="/console/investigations/{b}">triaged separately</a>' in page
    assert triage_rows(database_url) == 2


def test_a_separated_pair_never_joins_again_either_way(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket
) -> None:
    sock = buttons
    slack = FakeSlack(sock.url)
    steps = [*DONE, *DONE, *DONE, *DONE]
    with client(settings, fake_cluster, *steps, slack=slack.transport(), acme_channel=ACME) as c:
        a = separate(c, slack, sock)
        (b,) = set(ids(c)) - {a}
        wait_for(c, b, "done")
        # A new Alert in each: its own Triage, as for any group, never the other's.
        r = c.post(URL, json=with_fingerprint(ERRORS, "errors-2"), headers=HOOK).json()
        assert r["status"] == "accepted", r
        r = c.post(URL, json=with_fingerprint(LATENCY, "latency-2"), headers=HOOK).json()
        assert r["status"] == "accepted", r


def test_a_separated_pair_joins_again_in_a_later_incident(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The split holds within the window only: group keys outlive an incident."""
    sock = buttons
    slack = FakeSlack(sock.url)
    steps = [*DONE, *DONE, *DONE]
    with client(settings, fake_cluster, *steps, slack=slack.transport(), acme_channel=ACME) as c:
        a = separate(c, slack, sock)
        (b,) = set(ids(c)) - {a}
        wait_for(c, b, "done")
        later = api.now() + 31 * 60
        monkeypatch.setattr(api, "now", lambda: later)
        r = c.post(URL, json=with_fingerprint(ERRORS, "errors-2"), headers=HOOK).json()
        assert r["status"] == "accepted", r
        wait_for(c, r["investigation"], "done")
        joined = c.post(URL, json=with_fingerprint(LATENCY, "latency-2"), headers=HOOK).json()
        assert joined == {"status": "related", "investigation": r["investigation"]}


def test_over_budget_the_click_starts_nothing_and_keeps_the_button(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    settings.model_prices = {settings.model: HAIKU}
    sock = buttons
    slack = FakeSlack(sock.url)
    spent = used(call("TriageReport", "c1", **REPORT), 10_000, 0)  # 0.001 USD
    budget = {"monthly_budget_usd": 0.0005}
    with client(
        settings, fake_cluster, spent, slack=slack.transport(), acme_channel=ACME, acme=budget
    ) as c:
        a = c.post(URL, json=ERRORS, headers=HOOK).json()["investigation"]
        wait_for(c, a, "done")
        assert c.post(URL, json=LATENCY, headers=HOOK).json()["status"] == "related"
        until(lambda: has_button(slack))
        ts, value = related_post(slack)
        sock.send(click("triage_separately", value, message_ts=ts))
        until(lambda: len(ephemerals(slack)) == 1)
        ((_, text),) = ephemerals(slack)
        assert text.startswith("Not started. Contract 'acme' has used its monthly budget")
        assert ids(c) == [a]
        assert not [p for m, p, _ in slack.calls if m == "chat.update" and p["ts"] == ts]
    assert triage_rows(database_url) == 1
    with psycopg.connect(database_url) as conn:
        row = conn.execute("select separate_id from related_groups").fetchone()
    assert row == (None,)


def test_once_separated_the_groups_resolution_makes_only_its_own_triage_stale(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket
) -> None:
    pod = [{"labels": {"pod": "checkout-7d9f-abc"}}]
    errors = {**ERRORS, "alerts": [{**ERRORS["alerts"][0], **pod[0]}]}
    latency = {**LATENCY, "alerts": [{**LATENCY["alerts"][0], **pod[0]}]}
    sock = buttons
    slack = FakeSlack(sock.url)
    steps = [EVICT, EVICT, call("TriageReport", "c2", **REPORT)]
    with client(
        settings, fake_cluster, *steps, actions=True, slack=slack.transport(), acme_channel=ACME
    ) as c:
        a = c.post(URL, json=errors, headers=HOOK).json()["investigation"]
        wait_for(c, a, "awaiting_approval")
        assert c.post(URL, json=latency, headers=HOOK).json()["status"] == "related"
        until(lambda: has_button(slack))
        ts, value = related_post(slack)
        sock.send(click("triage_separately", value, message_ts=ts))
        until(lambda: len(ids(c)) == 2)
        (b,) = set(ids(c)) - {a}
        wait_for(c, b, "awaiting_approval")
        resolved = alert("g-latency", "PaymentsLatency", status="resolved")
        assert c.post(URL, json=resolved, headers=HOOK).json() == {
            "status": "stale",
            "investigations": [b],
        }
        wait_for(c, b, "done")
        assert wait_for(c, a, "awaiting_approval")["pending"]


def test_a_forged_click_cannot_separate_another_triages_group(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    """The related id must belong to the Triage the click names: here demo bank's
    related group, named with acme's Triage from acme's channel."""
    sock = buttons
    slack = FakeSlack(sock.url)
    with client(
        settings,
        fake_cluster,
        *DONE,
        *DONE,
        slack=slack.transport(),
        acme_channel=ACME,
        more=bank(),
    ) as c:
        a = c.post(URL, json=ERRORS, headers=HOOK).json()["investigation"]
        wait_for(c, a, "done")
        theirs = c.post(BANK_URL, json=ERRORS, headers=BANK_HOOK).json()["investigation"]
        wait_for(c, theirs, "done")
        assert c.post(BANK_URL, json=LATENCY, headers=BANK_HOOK).json()["status"] == "related"
        with psycopg.connect(database_url) as conn:
            row = conn.execute("select id from related_groups").fetchone()
        assert row is not None
        forged = json.dumps({"id": a, "related": row[0]})
        sock.send(click("triage_separately", forged))
        until(lambda: ephemerals(slack) == [(CLICKER, GONE)])
        assert sorted(ids(c)) == sorted([a, theirs])
    assert triage_rows(database_url) == 2


@pytest.mark.anyio
async def test_a_related_group_is_claimed_once(database_url: str) -> None:
    """Two claims, as two clicks racing past the read: one Triage, the other rolled back."""
    from aiops_agent.models import AlertGroup, Investigation
    from aiops_agent.store import Store, connect

    async with connect(database_url) as pool:
        store = Store(pool)
        await store.migrate()
        a = Investigation(id="a", contract_id="acme", title="a", started=api.now(), input=ERRORS)
        await store.insert(a)
        group = AlertGroup.model_validate(LATENCY)
        rid = await store.add_related("a", "acme", group, {"service": "payments"}, False, 1.0)
        first, second = (a.model_copy(update={"id": i, "group_key": "g-latency"}) for i in "bc")
        assert await store.separate(rid, "a", first)
        assert not await store.separate(rid, "a", second)
        assert await store.get("c") is None
        assert (await store.related_group(rid, "a") or {})["separate_id"] == "b"
