"""Each Investigation is one thread in its own Contract's Slack channel, with
approve / reject buttons for the Operator.

Slack's Web API is an httpx MockTransport: tests check the JSON actually sent.
Socket Mode is a real local websocket (FakeSocket) that sends click envelopes.
"""

import json
import logging
import queue
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from websockets.sync.server import ServerConnection, serve

from aiops_agent.api import create_app
from aiops_agent.config import Settings
from aiops_agent.slack import clean
from tests.conftest import REPORT, call, make_contract, make_fake_cluster, scripted
from tests.test_api import ALERT, AUTH, BANK_HOOK, BANK_URL, HOOK, RESOLVED, URL, client
from tests.test_restart import wait_for

ACME, BANK = "C0ACME0001", "C0BANK0001"
TOKEN = "xoxb-test-bot-token-1234567890"
EVICT = call(
    "kubernetes_evict_pod", "c1", cluster="test", namespace="shop", name="checkout-7d9f-abc"
)
REPORT_STEP = call("TriageReport", "c2", **REPORT)


class FakeSlack:
    """Records every Web API call. `answers` overrides the reply to the next calls.
    apps.connections.open (Socket Mode) answers socket_url and goes in `opens`."""

    def __init__(self, socket_url: str = "") -> None:
        self.calls: list[tuple[str, dict[str, Any], str]] = []
        self.answers: list[httpx.Response] = []
        self.ts = 0
        self.socket_url, self.opens = socket_url, list[str]()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[1]
        if method == "apps.connections.open":
            self.opens.append(request.headers["authorization"])
            return httpx.Response(200, json={"ok": True, "url": self.socket_url})
        self.calls.append((method, json.loads(request.content), request.headers["authorization"]))
        if self.answers:
            return self.answers.pop(0)
        self.ts += 1
        return httpx.Response(200, json={"ok": True, "ts": f"1700000000.{self.ts:06d}"})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def until(self, n: int) -> None:
        """Wait for n calls in all. The Hub saves a status before it posts it, so a
        test that stops the Hub right after seeing the status would cancel posts
        still in flight."""
        end = time.monotonic() + 5
        while len(self.calls) < n and time.monotonic() < end:
            time.sleep(0.02)
        assert len(self.calls) >= n, self.calls

    def channels(self) -> set[str]:
        return {payload["channel"] for _, payload, _ in self.calls}


@pytest.fixture(autouse=True)
def _slack(settings: Settings, database_url: str) -> None:
    settings.database_url = SecretStr(database_url)
    settings.slack_bot_token = SecretStr(TOKEN)


def done_once(settings: Settings, fake_cluster: Any, slack: FakeSlack, calls: int = 3) -> str:
    """One Investigation to done, then wait for its `calls` Slack calls (normally the
    parent, its update to done, and the Report reply)."""
    steps = [call("TriageReport", "c1", **REPORT)]
    calls_before = len(slack.calls)
    with client(settings, fake_cluster, *steps, slack=slack.transport(), acme_channel=ACME) as c:
        tid: str = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        slack.until(calls_before + calls)
    return tid


def test_one_thread_per_investigation(settings: Settings, fake_cluster: Any) -> None:
    slack = FakeSlack()
    tid = done_once(settings, fake_cluster, slack)
    (m1, parent, auth), (m2, update, _), (m3, reply, _) = slack.calls
    assert (m1, m2, m3) == ("chat.postMessage", "chat.update", "chat.postMessage")
    assert auth == f"Bearer {TOKEN}"
    assert "thread_ts" not in parent and "investigating" in parent["text"] and tid in parent["text"]
    assert update["ts"] == reply["thread_ts"] == "1700000000.000001"
    assert "done" in update["text"]
    first, *rest = reply["text"].splitlines()
    assert first.startswith("*checkout") and first.endswith("limit.*")  # bold, balanced
    assert "*Evidence*" in rest and any(line.startswith("• `kubernetes_pod_logs`") for line in rest)
    assert slack.channels() == {ACME}


def test_each_contract_posts_only_to_its_own_channel(settings: Settings, fake_cluster: Any) -> None:
    slack = FakeSlack()
    bank = make_contract(contract_id="bank", webhook_token="bank-token", slack_channel=BANK)
    steps = [call("TriageReport", "c1", **REPORT), call("TriageReport", "c2", **REPORT)]
    more = {"bank": (bank, make_fake_cluster())}
    with client(
        settings, fake_cluster, *steps, more=more, slack=slack.transport(), acme_channel=ACME
    ) as c:
        a = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, a, "done")
        slack.until(3)
        assert slack.channels() == {ACME}
        seen = len(slack.calls)
        b = c.post(BANK_URL, json=ALERT, headers=BANK_HOOK).json()["investigation"]
        wait_for(c, b, "done")
        slack.until(seen + 3)
    assert {p["channel"] for _, p, _ in slack.calls[seen:]} == {BANK}
    assert all("[bank]" not in p.get("text", "") for _, p, _ in slack.calls[:seen])


def test_slack_failures_are_logged_never_fatal(
    settings: Settings, fake_cluster: Any, caplog: pytest.LogCaptureFixture
) -> None:
    slack = FakeSlack()
    slack.answers = [httpx.Response(200, json={"ok": False, "error": "not_in_channel"})] * 5
    caplog.set_level(logging.WARNING, logger="aiops.slack")
    done_once(settings, fake_cluster, slack, calls=2)  # both parent attempts refused
    assert f"chat.postMessage to {ACME} failed: not_in_channel" in caplog.text
    assert TOKEN not in caplog.text


def test_a_failed_first_post_starts_the_thread_later(settings: Settings, fake_cluster: Any) -> None:
    slack = FakeSlack()
    slack.answers = [httpx.Response(200, json={"ok": False, "error": "ratelimited"})]
    done_once(settings, fake_cluster, slack)
    (_, first, _), (m2, parent, _), (m3, reply, _) = slack.calls
    assert "investigating" in first["text"]  # lost
    assert m2 == m3 == "chat.postMessage" and "thread_ts" not in parent and "done" in parent["text"]
    assert reply["thread_ts"] == "1700000000.000001"


def test_a_429_is_retried_once_after_retry_after(settings: Settings, fake_cluster: Any) -> None:
    slack = FakeSlack()
    slack.answers = [httpx.Response(429, headers={"Retry-After": "0"})]
    done_once(settings, fake_cluster, slack, calls=4)
    assert [m for m, _, _ in slack.calls[:2]] == ["chat.postMessage", "chat.postMessage"]
    assert "investigating" in slack.calls[1][1]["text"]  # the same parent, retried at once
    assert slack.calls[-1][1]["thread_ts"] == "1700000000.000001"


def test_after_a_restart_the_same_thread_continues(settings: Settings, fake_cluster: Any) -> None:
    slack = FakeSlack()
    with client(
        settings, fake_cluster, EVICT, actions=True, slack=slack.transport(), acme_channel=ACME
    ) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "awaiting_approval")
        slack.until(3)  # parent, its update, the Proposed actions
    thread = slack.calls[0][1]
    assert "waiting for your approval" in slack.calls[1][1]["text"]
    assert buttons(slack) == {}  # no app token: no buttons, the API decides
    assert "kubernetes_evict_pod" in slack.calls[2][1]["text"]
    assert "Decide with `POST" in slack.calls[2][1]["text"]
    with client(
        settings,
        fake_cluster,
        REPORT_STEP,
        actions=True,
        slack=slack.transport(),
        acme_channel=ACME,
    ) as c:
        c.post(f"/investigations/{tid}/decision", json={"approve": True}, headers=AUTH)
        wait_for(c, tid, "done")
        slack.until(6)  # "investigating" again, "done", the Report
    later = slack.calls[3:]
    assert {p.get("ts") or p.get("thread_ts") for _, p, _ in later} == {"1700000000.000001"}
    assert sum(m == "chat.postMessage" and "thread_ts" not in p for m, p, _ in later) == 0
    assert "thread_ts" not in thread


def test_no_channel_no_posts_and_duplicates_post_nothing(
    settings: Settings, fake_cluster: Any
) -> None:
    slack = FakeSlack()
    steps = [call("TriageReport", "c1", **REPORT)]
    with client(settings, fake_cluster, *steps, slack=slack.transport()) as c:
        other = {**ALERT, "groupKey": "no-channel"}  # its own group: no dedup below
        wait_for(c, c.post(URL, json=other, headers=HOOK).json()["investigation"], "done")
        time.sleep(0.5)  # no channel: nothing should arrive
    assert slack.calls == []
    tid = done_once(settings, fake_cluster, slack)
    seen = len(slack.calls)
    with client(settings, fake_cluster, slack=slack.transport(), acme_channel=ACME) as c:
        assert c.post(URL, json=ALERT, headers=HOOK).json()["status"] == "duplicate"
        assert c.post(URL, json=RESOLVED, headers=HOOK).json()["status"] == "ignored"
        time.sleep(0.5)  # nothing should arrive
    assert len(slack.calls) == seen and tid


def test_slack_markup_in_alerts_arrives_as_text(settings: Settings, fake_cluster: Any) -> None:
    slack = FakeSlack()
    hostile = {
        **ALERT,
        "commonLabels": {"alertname": "<!channel> pay me <@U123>", "namespace": "x"},
    }
    steps = [call("TriageReport", "c1", **REPORT)]
    with client(settings, fake_cluster, *steps, slack=slack.transport(), acme_channel=ACME) as c:
        wait_for(c, c.post(URL, json=hostile, headers=HOOK).json()["investigation"], "done")
        slack.until(3)
    texts = " ".join(p.get("text", "") for _, p, _ in slack.calls)
    assert "&lt;!channel&gt; pay me &lt;@U123&gt;" in texts
    assert "<!channel>" not in texts and "<@U123>" not in texts


def test_clean_escapes_then_redacts() -> None:
    out = clean("<b> & token=abcd1234efgh")
    assert out == "&lt;b&gt; &amp; token=[REDACTED]"


# Buttons over Socket Mode.

OPERATOR, STRANGER = "U0OPERATOR1", "U0STRANGER1"
EVICT_AGAIN = call(
    "kubernetes_evict_pod", "c3", cluster="test", namespace="shop", name="checkout-7d9f-abc"
)


class FakeSocket:
    """Slack's Socket Mode end: a local websocket that sends envelopes and checks
    each one is acked."""

    def __init__(self) -> None:
        self.ws: ServerConnection | None = None
        self.acks: queue.Queue[dict[str, Any]] = queue.Queue()
        self.server = serve(self._connected, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"ws://127.0.0.1:{self.server.socket.getsockname()[1]}"

    def _connected(self, ws: ServerConnection) -> None:
        self.ws = ws
        ws.send(json.dumps({"type": "hello"}))
        for raw in ws:
            self.acks.put(json.loads(raw))

    def connection(self) -> ServerConnection:
        end = time.monotonic() + 5
        while self.ws is None and time.monotonic() < end:
            time.sleep(0.02)
        assert self.ws is not None, "the Hub never connected"
        return self.ws

    def send(self, payload: dict[str, Any]) -> None:
        envelope = str(uuid.uuid4())
        msg = {"envelope_id": envelope, "type": "interactive", "payload": payload}
        self.connection().send(json.dumps(msg))
        assert self.acks.get(timeout=5) == {"envelope_id": envelope}


@pytest.fixture
def sock(settings: Settings) -> Iterator[FakeSocket]:
    settings.slack_app_token = SecretStr("xapp-test-app-token")
    settings.slack_operator_id = OPERATOR
    s = FakeSocket()
    yield s
    s.server.shutdown()


def click(action_id: str, value: str, user: str = OPERATOR, channel: str = ACME) -> dict[str, Any]:
    return {
        "type": "block_actions",
        "user": {"id": user},
        "channel": {"id": channel},
        "trigger_id": "trigger-1",
        "actions": [{"action_id": action_id, "value": value}],
    }


def submit(metadata: str, reason: str, user: str = OPERATOR) -> dict[str, Any]:
    value = {"reason": {"reason": {"type": "plain_text_input", "value": reason}}}
    view = {"callback_id": "reject", "private_metadata": metadata, "state": {"values": value}}
    return {"type": "view_submission", "user": {"id": user}, "view": view}


def buttons(slack: FakeSlack) -> dict[str, dict[str, Any]]:
    """The buttons on the parent as last posted or updated, by action_id."""
    parents = [p for m, p, _ in slack.calls if m in ("chat.postMessage", "chat.update")]
    last = [p for p in parents if "thread_ts" not in p][-1]["blocks"]
    return {e["action_id"]: e for b in last if b["type"] == "actions" for e in b["elements"]}


def replies(slack: FakeSlack) -> list[str]:
    return [p["text"] for m, p, _ in slack.calls if m == "chat.postMessage" and "thread_ts" in p]


def ephemerals(slack: FakeSlack) -> list[tuple[str, str]]:
    return [(p["user"], p["text"]) for m, p, _ in slack.calls if m == "chat.postEphemeral"]


def until(check: Any) -> None:
    end = time.monotonic() + 5
    while not check() and time.monotonic() < end:
        time.sleep(0.02)
    assert check()


@contextmanager
def paused(
    settings: Settings, fake_cluster: Any, slack: FakeSlack, *after: Any
) -> Iterator[tuple[TestClient, str]]:
    """An Investigation waiting for approval of EVICT, its buttons posted."""
    with client(
        settings,
        fake_cluster,
        EVICT,
        *after,
        actions=True,
        slack=slack.transport(),
        acme_channel=ACME,
    ) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "awaiting_approval")
        slack.until(3)  # parent, its update with the buttons, the Proposed actions
        yield c, tid


def decided_by(database_url: str) -> list[tuple[bool, str, str]]:
    with psycopg.connect(database_url) as conn:
        rows = conn.execute("select approve, decided_by, message from decisions order by id")
        return [(r[0], r[1], r[2]) for r in rows.fetchall()]


def test_the_operator_approves_once_with_the_button(
    settings: Settings, fake_cluster: Any, sock: FakeSocket, database_url: str
) -> None:
    slack = FakeSlack(sock.url)
    with paused(settings, fake_cluster, slack, REPORT_STEP) as (c, tid):
        approve = buttons(slack)["approve"]
        assert set(buttons(slack)) == {"approve", "reject"}
        assert json.loads(approve["value"])["id"] == tid
        assert approve["confirm"]["text"]["text"] == "kubernetes_evict_pod"
        assert "on the message above" in replies(slack)[-1]
        sock.send(click("approve", approve["value"]))
        wait_for(c, tid, "done")
        until(lambda: any("Approved by <@U0OPERATOR1>" in r for r in replies(slack)))
        until(lambda: "done" in slack.calls[-2][1]["text"])  # parent done, then the Report
        assert buttons(slack) == {}
        sock.send(click("approve", approve["value"]))  # a second click
        until(lambda: ephemerals(slack) == [(OPERATOR, ANY_DECIDED)])
    assert slack.opens[0] == "Bearer xapp-test-app-token"
    assert decided_by(database_url) == [(True, "slack:U0OPERATOR1", "")]


ANY_DECIDED = "Already decided or Stale: nothing to decide."


def test_only_the_operator_decides_and_only_from_its_channel(
    settings: Settings, fake_cluster: Any, sock: FakeSocket, database_url: str
) -> None:
    slack = FakeSlack(sock.url)
    with paused(settings, fake_cluster, slack) as (c, tid):
        value = buttons(slack)["approve"]["value"]
        sock.send(click("approve", value, user=STRANGER))
        sock.send(click("reject", value, user=STRANGER))
        sock.send(submit(json.dumps({**json.loads(value), "channel": ACME}), "no", user=STRANGER))
        sock.send(click("approve", value, channel=BANK))  # the Operator, in another channel
        until(lambda: len(ephemerals(slack)) == 4)
        assert wait_for(c, tid, "awaiting_approval")["pending"]
    assert ephemerals(slack)[:3] == [(STRANGER, "Only the Operator can decide.")] * 3
    assert ephemerals(slack)[3] == (OPERATOR, "That Investigation isn't in this channel.")
    assert {p["channel"] for m, p, _ in slack.calls if m == "chat.postEphemeral"} == {ACME, BANK}
    assert all(m != "views.open" for m, _, _ in slack.calls)
    assert decided_by(database_url) == []


def test_an_old_pause_button_cannot_decide_a_new_pause(
    settings: Settings, fake_cluster: Any, sock: FakeSocket, database_url: str
) -> None:
    slack = FakeSlack(sock.url)
    with paused(settings, fake_cluster, slack, EVICT_AGAIN, REPORT_STEP) as (c, tid):
        first = buttons(slack)["approve"]["value"]
        sock.send(click("approve", first))
        until(lambda: buttons(slack).get("approve", {}).get("value", first) != first)
        second = buttons(slack)["approve"]["value"]
        sock.send(click("approve", first))  # late, from the first pause
        sock.send(click("reject", first))
        until(lambda: len(ephemerals(slack)) == 2)
        assert wait_for(c, tid, "awaiting_approval")["pending"]
        sock.send(click("approve", second))
        wait_for(c, tid, "done")
    assert ephemerals(slack) == [(OPERATOR, ANY_DECIDED)] * 2
    assert [d[0] for d in decided_by(database_url)] == [True, True]


def test_reject_asks_for_a_reason_and_claims_only_on_submit(
    settings: Settings, fake_cluster: Any, sock: FakeSocket, database_url: str
) -> None:
    slack = FakeSlack(sock.url)
    with paused(settings, fake_cluster, slack, REPORT_STEP) as (c, tid):
        sock.send(click("reject", buttons(slack)["reject"]["value"]))
        until(lambda: any(m == "views.open" for m, _, _ in slack.calls))
        (view_call,) = [p for m, p, _ in slack.calls if m == "views.open"]
        assert view_call["trigger_id"] == "trigger-1"
        assert view_call["view"]["callback_id"] == "reject"
        assert wait_for(c, tid, "awaiting_approval")["pending"]  # the modal can still be cancelled
        sock.send(submit(view_call["view"]["private_metadata"], "  <!here> limits, not the pod  "))
        wait_for(c, tid, "done")
        until(
            lambda: any(
                r.startswith(":no_entry: Rejected by <@U0OPERATOR1>") for r in replies(slack)
            )
        )
    assert any("&lt;!here&gt; limits, not the pod" in r for r in replies(slack))
    assert decided_by(database_url) == [(False, "slack:U0OPERATOR1", "<!here> limits, not the pod")]


def test_stale_and_api_decisions_take_the_buttons_away(
    settings: Settings, fake_cluster: Any, sock: FakeSocket
) -> None:
    slack = FakeSlack(sock.url)
    with paused(settings, fake_cluster, slack, REPORT_STEP) as (c, tid):
        value = buttons(slack)["approve"]["value"]
        decision = c.post(f"/investigations/{tid}/decision", json={"approve": True}, headers=AUTH)
        assert decision.status_code == 202
        wait_for(c, tid, "done")
        until(lambda: ":white_check_mark: Approved through the API." in replies(slack))
        assert buttons(slack) == {}
        sock.send(click("approve", value))
        until(lambda: ephemerals(slack) == [(OPERATOR, ANY_DECIDED)])
    settings.decision_timeout_seconds = 0
    slack = FakeSlack(sock.url)
    sock.ws = None
    stale_alert = {**ALERT, "groupKey": "stale"}
    with client(
        settings,
        fake_cluster,
        EVICT,
        REPORT_STEP,
        actions=True,
        slack=slack.transport(),
        acme_channel=ACME,
    ) as c:
        tid = c.post(URL, json=stale_alert, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        until(lambda: any(r.startswith(":hourglass: Stale") for r in replies(slack)))
        until(lambda: "done" in slack.calls[-2][1]["text"])
        assert buttons(slack) == {}


def test_socket_mode_reconnects_when_slack_says_disconnect(
    settings: Settings, fake_cluster: Any, sock: FakeSocket
) -> None:
    slack = FakeSlack(sock.url)
    with client(settings, fake_cluster, slack=slack.transport(), acme_channel=ACME):
        first = sock.connection()
        sock.ws = None
        first.send(json.dumps({"type": "disconnect", "reason": "refresh_requested"}))
        assert sock.connection() is not first
    assert len(slack.opens) == 2


def test_buttons_need_the_bot_token_and_an_operator_id(settings: Settings) -> None:
    settings.approver_token = SecretStr("approver-token")
    settings.slack_app_token = SecretStr("xapp-test")
    for bot, operator in ((TOKEN, None), (TOKEN, "not-a-user"), (None, OPERATOR)):
        settings.slack_bot_token = SecretStr(bot) if bot else None
        settings.slack_operator_id = operator
        with pytest.raises(RuntimeError, match="AIOPS_SLACK_OPERATOR_ID"):
            create_app(settings, scripted(), by_id={})


def test_bad_payloads_and_a_dead_socket_are_logged_never_fatal(
    settings: Settings, fake_cluster: Any, sock: FakeSocket, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    slack = FakeSlack(sock.url)
    with paused(settings, fake_cluster, slack, REPORT_STEP) as (c, tid):
        sock.send({"type": "shortcut", "user": {"id": OPERATOR}})  # not ours: ignored
        sock.send({"type": "block_actions", "user": {"id": OPERATOR}})  # no actions
        until(lambda: "slack interaction block_actions failed" in caplog.text)
        sock.send(click("approve", buttons(slack)["approve"]["value"]))  # still listening
        wait_for(c, tid, "done")
    dead = FakeSlack("ws://127.0.0.1:1")
    with client(settings, fake_cluster, slack=dead.transport()):
        until(lambda: "slack socket mode: " in caplog.text)
