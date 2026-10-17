"""Each Investigation is one thread in its own Contract's Slack channel.

Slack's Web API is an httpx MockTransport: tests check the JSON actually sent.
"""

import json
import logging
import time
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from aiops_agent.config import Settings
from aiops_agent.slack import clean
from tests.conftest import REPORT, call, make_contract, make_fake_cluster
from tests.test_api import ALERT, AUTH, BANK_HOOK, BANK_URL, HOOK, RESOLVED, URL, client
from tests.test_restart import wait_for

ACME, BANK = "C0ACME0001", "C0BANK0001"
TOKEN = "xoxb-test-bot-token-1234567890"
EVICT = call(
    "kubernetes_evict_pod", "c1", cluster="test", namespace="shop", name="checkout-7d9f-abc"
)
REPORT_STEP = call("TriageReport", "c2", **REPORT)


class FakeSlack:
    """Records every Web API call. `answers` overrides the reply to the next calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], str]] = []
        self.answers: list[httpx.Response] = []
        self.ts = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[1]
        self.calls.append((method, json.loads(request.content), request.headers["authorization"]))
        if self.answers:
            return self.answers.pop(0)
        self.ts += 1
        return httpx.Response(200, json={"ok": True, "ts": f"1700000000.{self.ts:06d}"})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def channels(self) -> set[str]:
        return {payload["channel"] for _, payload, _ in self.calls}


@pytest.fixture(autouse=True)
def _slack(settings: Settings, database_url: str) -> None:
    settings.database_url = SecretStr(database_url)
    settings.slack_bot_token = SecretStr(TOKEN)


def done_once(settings: Settings, fake_cluster: Any, slack: FakeSlack) -> str:
    steps = [call("TriageReport", "c1", **REPORT)]
    with client(settings, fake_cluster, *steps, slack=slack.transport(), acme_channel=ACME) as c:
        tid: str = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
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
    assert "JVM runs out of memory" in reply["text"]
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
        assert slack.channels() == {ACME}
        seen = len(slack.calls)
        b = c.post(BANK_URL, json=ALERT, headers=BANK_HOOK).json()["investigation"]
        wait_for(c, b, "done")
    assert {p["channel"] for _, p, _ in slack.calls[seen:]} == {BANK}
    assert all("[bank]" not in p.get("text", "") for _, p, _ in slack.calls[:seen])


def test_slack_failures_are_logged_never_fatal(
    settings: Settings, fake_cluster: Any, caplog: pytest.LogCaptureFixture
) -> None:
    slack = FakeSlack()
    slack.answers = [httpx.Response(200, json={"ok": False, "error": "not_in_channel"})] * 5
    caplog.set_level(logging.WARNING, logger="aiops.slack")
    done_once(settings, fake_cluster, slack)
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
    done_once(settings, fake_cluster, slack)
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
    thread = slack.calls[0][1]
    assert "waiting for your approval" in slack.calls[1][1]["text"]
    assert "kubernetes_evict_pod" in slack.calls[2][1]["text"]
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
        wait_for(c, c.post(URL, json=ALERT, headers=HOOK).json()["investigation"], "done")
    assert slack.calls == []
    tid = done_once(settings, fake_cluster, slack)
    seen = len(slack.calls)
    with client(settings, fake_cluster, slack=slack.transport(), acme_channel=ACME) as c:
        assert c.post(URL, json=ALERT, headers=HOOK).json()["status"] == "duplicate"
        assert c.post(URL, json=RESOLVED, headers=HOOK).json()["status"] == "ignored"
        time.sleep(0.2)
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
    texts = " ".join(p.get("text", "") for _, p, _ in slack.calls)
    assert "&lt;!channel&gt; pay me &lt;@U123&gt;" in texts
    assert "<!channel>" not in texts and "<@U123>" not in texts


def test_clean_escapes_then_redacts() -> None:
    out = clean("<b> & token=abcd1234efgh")
    assert out == "&lt;b&gt; &amp; token=[REDACTED]"
