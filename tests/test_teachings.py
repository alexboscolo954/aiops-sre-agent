"""Teachings, part a (slice 7.3): the Operator's feedback on a Report, a Teaching
drafted from a correction or a rejection reason, and its review in Slack and the
console. Only approved Teachings, and only the Contract's own, reach the drafter."""

# ruff: noqa: F811 - sock is test_slack's fixture, imported for these tests
import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, ClassVar

import psycopg
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import BaseMessage
from pydantic import SecretStr

from aiops_agent import teachings
from aiops_agent.config import Settings
from aiops_agent.store import Store, connect
from tests import test_api
from tests.conftest import REPORT, ScriptedModel, call
from tests.test_api import ALERT, AUTH, BANK_HOOK, BANK_URL, HOOK, URL, bank, client
from tests.test_console import OPERATOR as LOGIN
from tests.test_console import SAME, VIEW
from tests.test_cost import HAIKU, used
from tests.test_restart import wait_for
from tests.test_slack import (
    ACME,
    EVICT,
    OPERATOR,
    REPORT_STEP,
    STRANGER,
    TOKEN,
    FakeSlack,
    FakeSocket,
    click,
    ephemerals,
    paused,
    replies,
    sock,  # noqa: F401
    until,
)
from tests.test_slack import (
    buttons as slack_buttons,
)
from tests.test_slack import submit as reject_submit

LESSON = "checkout's memory limit belongs to the platform team: recommend a ticket, never a raise."
CORRECTION = "Wrong: the platform team owns that limit, we never change it ourselves."
GONE = "Already decided, or not a Teaching of this thread."


def draft(call_id: str = "d1", **fields: Any) -> Any:
    return call(
        "TeachingDraft", call_id, **{"text": LESSON, "alerts": ["KubePodCrashLooping"]} | fields
    )


class Recording(ScriptedModel):
    """Scripted, and keeps what each model call was sent."""

    sent: ClassVar[list[list[BaseMessage]]] = []

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        Recording.sent.append(messages)
        return super()._generate(messages, *args, **kwargs)


@pytest.fixture(autouse=True)
def recording(monkeypatch: pytest.MonkeyPatch) -> None:
    Recording.sent = []
    monkeypatch.setattr(test_api, "scripted", lambda *s: Recording(messages=iter(s)))


@pytest.fixture
def buttons(settings: Settings, sock: FakeSocket, database_url: str) -> FakeSocket:
    settings.database_url = SecretStr(database_url)
    settings.slack_bot_token = SecretStr(TOKEN)
    settings.console_operators = {LOGIN}
    return sock


@contextmanager
def done(
    settings: Settings, fake_cluster: Any, slack: FakeSlack, *after: Any, **kw: Any
) -> Iterator[tuple[TestClient, str]]:
    """A finished Triage, its Report and feedback buttons posted."""
    with client(
        settings,
        fake_cluster,
        REPORT_STEP,
        *after,
        slack=slack.transport(),
        acme_channel=ACME,
        **kw,
    ) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        until(lambda: "feedback_right" in posted(slack))
        yield c, tid


def posted(slack: FakeSlack) -> dict[str, tuple[str, dict[str, Any]]]:
    """Every button posted in a thread so far, newest wins: action_id -> (the post's
    ts, the button). FakeSlack numbers every call."""
    found = {}
    for i, (method, payload, _) in enumerate(slack.calls):
        if method != "chat.postMessage" or "thread_ts" not in payload:
            continue
        for block in payload.get("blocks", []):
            for e in block.get("elements", []):
                found[e["action_id"]] = (f"1700000000.{i + 1:06d}", e)
    return found


def press(sock: FakeSocket, slack: FakeSlack, action_id: str, user: str = OPERATOR) -> None:
    ts, button = posted(slack)[action_id]
    sock.send(click(action_id, button["value"], user=user, message_ts=ts))


def opened(slack: FakeSlack) -> dict[str, Any]:
    (view,) = [p["view"] for m, p, _ in slack.calls if m == "views.open"][-1:]
    return view


def submit(view: dict[str, Any], value: str, user: str = OPERATOR) -> dict[str, Any]:
    callback = view["callback_id"]
    values = {callback: {callback: {"type": "plain_text_input", "value": value}}}
    return {
        "type": "view_submission",
        "user": {"id": user},
        "view": {
            "callback_id": callback,
            "private_metadata": view["private_metadata"],
            "state": {"values": values},
        },
    }


def rows(database_url: str, sql: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(database_url) as conn:
        return [tuple(r) for r in conn.execute(sql).fetchall()]


def correct_it(sock: FakeSocket, slack: FakeSlack, text: str = CORRECTION) -> None:
    press(sock, slack, "feedback_wrong")
    until(lambda: any(m == "views.open" for m, _, _ in slack.calls))
    sock.send(submit(opened(slack), text))


# Feedback


def test_right_is_recorded_and_drafts_nothing(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    slack = FakeSlack(buttons.url)
    with done(settings, fake_cluster, slack) as (_c, tid):
        right = posted(slack)["feedback_right"][1]
        assert json.loads(right["value"]) == {"id": tid}
        press(buttons, slack, "feedback_right")
        until(lambda: ":+1: <@U0OPERATOR1> marked this Report right." in replies(slack))
    assert rows(database_url, "select correct, correction, by from feedback") == [
        (True, None, "slack:U0OPERATOR1")
    ]
    assert rows(database_url, "select count(*) from teachings") == [(0,)]


def test_a_correction_proposes_a_teaching_and_approve_takes_it_once(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    slack = FakeSlack(buttons.url)
    with done(settings, fake_cluster, slack, draft()) as (_c, tid):
        correct_it(buttons, slack)
        until(lambda: "teaching_approve" in posted(slack))
        assert f":-1: <@U0OPERATOR1> marked this Report wrong: {CORRECTION}" in replies(slack)
        ts, approve = posted(slack)["teaching_approve"]
        assert set(posted(slack)) >= {"teaching_approve", "teaching_edit", "teaching_reject"}
        ((tid_, status, text, source, slack_ts),) = rows(
            database_url, "select id, status, text, source_id, slack_ts from teachings"
        )
        assert (status, text, source, slack_ts) == ("proposed", LESSON, tid, ts)
        assert json.loads(approve["value"]) == {"id": tid, "teaching": tid_}
        press(buttons, slack, "teaching_approve")
        press(buttons, slack, "teaching_approve")  # a second click
        until(lambda: ephemerals(slack) == [(OPERATOR, GONE)])
        (update,) = [p for m, p, _ in slack.calls if m == "chat.update" and p["ts"] == ts]
        assert update["blocks"] == [] and "Approved by <@U0OPERATOR1>." in update["text"]
    assert rows(database_url, "select status, decided_by, correction from teachings") == [
        ("approved", "slack:U0OPERATOR1", CORRECTION)
    ]
    assert rows(database_url, "select correct, correction from feedback") == [(False, CORRECTION)]


def test_edit_approves_exactly_the_text_submitted(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    slack = FakeSlack(buttons.url)
    with done(settings, fake_cluster, slack, draft()) as (_c, _tid):
        correct_it(buttons, slack)
        until(lambda: "teaching_edit" in posted(slack))
        slack.calls = [x for x in slack.calls if x[0] != "views.open"]
        press(buttons, slack, "teaching_edit")
        until(lambda: any(m == "views.open" for m, _, _ in slack.calls))
        view = opened(slack)
        assert view["blocks"][0]["element"]["initial_value"] == LESSON
        assert view["blocks"][0]["element"]["max_length"] == teachings.LIMIT
        buttons.send(submit(view, "Ticket the platform team for checkout limits."))
        until(lambda: rows(database_url, "select status from teachings") == [("approved",)])
        buttons.send(submit(view, "A second edit after approval."))  # changes nothing
        until(lambda: ephemerals(slack) == [(OPERATOR, GONE)])
    assert rows(database_url, "select text from teachings") == [
        ("Ticket the platform team for checkout limits.",)
    ]


def test_an_edit_too_long_changes_nothing(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    """Slack's own max_length isn't a check: the Hub refuses it too."""
    slack = FakeSlack(buttons.url)
    with done(settings, fake_cluster, slack, draft()):
        correct_it(buttons, slack)
        until(lambda: "teaching_edit" in posted(slack))
        press(buttons, slack, "teaching_edit")
        until(lambda: opened(slack)["callback_id"] == "teaching_edit")
        buttons.send(submit(opened(slack), "x" * 501))
        size = f"A Teaching is 1 to {teachings.LIMIT} characters: nothing changed."
        until(lambda: ephemerals(slack) == [(OPERATOR, size)])
    assert rows(database_url, "select status, text from teachings") == [("proposed", LESSON)]


def test_reject(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    slack = FakeSlack(buttons.url)
    with done(settings, fake_cluster, slack, draft()) as (_c, _tid):
        correct_it(buttons, slack)
        until(lambda: "teaching_reject" in posted(slack))
        press(buttons, slack, "teaching_reject")
        until(lambda: rows(database_url, "select status from teachings") == [("rejected",)])
        until(
            lambda: any(
                m == "chat.update" and "Rejected by" in p["text"] for m, p, _ in slack.calls
            )
        )


def test_only_the_operator_and_only_a_finished_report(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    slack = FakeSlack(buttons.url)
    with done(settings, fake_cluster, slack) as (_c, tid):
        press(buttons, slack, "feedback_right", user=STRANGER)
        until(lambda: ephemerals(slack) == [(STRANGER, "Only the Operator can decide.")])
        forged = json.dumps({"id": tid, "teaching": 1})
        buttons.send(click("teaching_approve", forged))  # no such Teaching here
        until(lambda: (OPERATOR, GONE) in ephemerals(slack))
    assert rows(database_url, "select count(*) from feedback") == [(0,)]


def test_slack_feedback_is_for_a_finished_triage_only(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    slack = FakeSlack(buttons.url)
    with client(
        settings, fake_cluster, EVICT, actions=True, slack=slack.transport(), acme_channel=ACME
    ) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "awaiting_approval")
        for action in ("feedback_right", "feedback_wrong"):
            buttons.send(click(action, json.dumps({"id": tid})))  # forged: no Report yet
        nope = (OPERATOR, "Feedback is for a finished Triage Report.")
        until(lambda: ephemerals(slack) == [nope, nope])
    assert rows(database_url, "select count(*) from feedback") == [(0,)]
    assert not [m for m, _, _ in slack.calls if m == "views.open"]


# Drafting


def test_the_drafter_sees_only_the_contracts_approved_teachings(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    slack = FakeSlack(buttons.url)
    with done(settings, fake_cluster, slack, draft(), more=bank()) as (_c, _tid):
        with psycopg.connect(database_url) as conn:
            for contract, status, text in [
                ("acme", "approved", "ACME-APPROVED lesson"),
                ("acme", "proposed", "ACME-PROPOSED lesson"),
                ("acme", "rejected", "ACME-REJECTED lesson"),
                ("acme", "retired", "ACME-RETIRED lesson"),
                ("bank", "approved", "BANK-APPROVED lesson"),
            ]:
                conn.execute(
                    "insert into teachings (contract_id, text, status, proposed_at) "
                    "values (%s, %s, %s, 0)",
                    (contract, text, status),
                )
        correct_it(buttons, slack)
        until(lambda: "teaching_approve" in posted(slack))
    sent = " ".join(str(m.content) for m in Recording.sent[-1])
    assert "ACME-APPROVED" in sent and CORRECTION in sent and REPORT["summary"] in sent
    for never in ("ACME-PROPOSED", "ACME-REJECTED", "ACME-RETIRED", "BANK-APPROVED"):
        assert never not in sent, never


def test_a_duplicate_is_not_queued(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    """The same words as an approved Teaching, or the model naming it a duplicate."""
    slack = FakeSlack(buttons.url)
    same_words = draft(text=LESSON.upper() + "!")
    named = draft("d2", text="Something else entirely.", duplicate_of=1)
    with done(settings, fake_cluster, slack, same_words, named) as (_c, _tid):
        with psycopg.connect(database_url) as conn:
            conn.execute(
                "insert into teachings (id, contract_id, text, status, proposed_at) "
                "values (1, 'acme', %s, 'approved', 0)",
                (LESSON,),
            )
        correct_it(buttons, slack)
        until(
            lambda: (
                replies(slack).count(":repeat: Already taught, or waiting for review: Teaching #1.")
                == 1
            )
        )
        correct_it(buttons, slack, "Another correction.")
        until(
            lambda: (
                replies(slack).count(":repeat: Already taught, or waiting for review: Teaching #1.")
                == 2
            )
        )
    assert rows(database_url, "select id from teachings") == [(1,)]


def test_approving_a_contradiction_retires_the_old_teaching(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    slack = FakeSlack(buttons.url)
    with done(settings, fake_cluster, slack, draft(contradicts=1)) as (_c, _tid):
        with psycopg.connect(database_url) as conn:
            conn.execute(
                "insert into teachings (id, contract_id, text, status, proposed_at) "
                "values (1, 'acme', 'Raise checkout limits yourself.', 'approved', 0), "
                "(2, 'bank', 'A bank lesson.', 'approved', 0)"
            )
            conn.execute("select setval('teachings_id_seq', 2)")
        correct_it(buttons, slack)
        until(lambda: "teaching_approve" in posted(slack))
        assert any("contradicts Teaching #1" in r for r in replies(slack))
        press(buttons, slack, "teaching_approve")
        until(
            lambda: any("Teaching #1 is retired." in p.get("text", "") for _, p, _ in slack.calls)
        )
    assert rows(database_url, "select id, status from teachings order by id") == [
        (1, "retired"),
        (2, "approved"),
        (3, "approved"),
    ]


def test_a_draft_is_stored_redacted_as_its_post_shows_it(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    slack = FakeSlack(buttons.url)
    with done(settings, fake_cluster, slack, draft(text="Log in with password=hunter2secret.")):
        correct_it(buttons, slack)
        until(lambda: "teaching_approve" in posted(slack))
        press(buttons, slack, "teaching_approve")
        until(lambda: rows(database_url, "select status from teachings") == [("approved",)])
    assert rows(database_url, "select text from teachings") == [
        ("Log in with password=[REDACTED]",)
    ]


def test_an_id_the_model_invents_is_dropped(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    slack = FakeSlack(buttons.url)
    with done(settings, fake_cluster, slack, draft(duplicate_of=99, contradicts=98)) as (_c, _tid):
        correct_it(buttons, slack)
        until(lambda: "teaching_approve" in posted(slack))
    assert rows(database_url, "select status, contradicts from teachings") == [("proposed", None)]


def test_an_unusable_draft_says_so_and_keeps_the_feedback(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    slack = FakeSlack(buttons.url)
    with done(settings, fake_cluster, slack, draft(text="x" * 501)) as (_c, _tid):
        correct_it(buttons, slack)
        note = ":warning: Couldn't draft a Teaching from that: write one on the console."
        until(lambda: note in replies(slack))
    assert rows(database_url, "select count(*) from teachings") == [(0,)]
    assert rows(database_url, "select correct from feedback") == [(False,)]


def test_over_budget_nothing_is_drafted(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    settings.model_prices = {settings.model: HAIKU}
    slack = FakeSlack(buttons.url)
    spent = used(call("TriageReport", "c2", **REPORT), 10_000, 0)  # 0.001 USD
    with client(
        settings,
        fake_cluster,
        spent,
        slack=slack.transport(),
        acme_channel=ACME,
        acme={"monthly_budget_usd": 0.0005},
    ) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        until(lambda: "feedback_wrong" in posted(slack))
        correct_it(buttons, slack)
        until(lambda: any(r.startswith(":no_entry: No Teaching drafted.") for r in replies(slack)))
    assert len(Recording.sent) == 1  # the Triage only
    assert rows(database_url, "select correct from feedback") == [(False,)]


def test_the_drafts_cost_is_its_investigations(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    settings.model_prices = {settings.model: HAIKU}
    slack = FakeSlack(buttons.url)
    with done(settings, fake_cluster, slack, used(draft(), 2_000, 100)) as (_c, tid):
        correct_it(buttons, slack)
        until(lambda: "teaching_approve" in posted(slack))
    assert rows(database_url, "select investigation_id, input_tokens from usage") == [(tid, 2_000)]


# A rejection reason


def test_a_typed_rejection_reason_drafts_after_the_run(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    slack = FakeSlack(buttons.url)
    with client(
        settings,
        fake_cluster,
        EVICT,
        REPORT_STEP,
        draft(),
        actions=True,
        slack=slack.transport(),
        acme_channel=ACME,
    ) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "awaiting_approval")
        r = c.post(
            f"/investigations/{tid}/decision",
            json={"approve": False, "message": "Never evict checkout: page the team."},
            headers=AUTH,
        )
        assert r.status_code == 202
        wait_for(c, tid, "done")
        until(lambda: "teaching_approve" in posted(slack))
    ((correction,),) = rows(database_url, "select correction from teachings")
    assert correction == (
        "The Operator rejected the proposed kubernetes_evict_pod, saying: "
        "Never evict checkout: page the team."
    )
    assert REPORT["summary"] in " ".join(str(m.content) for m in Recording.sent[-1])


def test_a_reason_typed_in_slacks_reject_form_drafts_too(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    slack = FakeSlack(buttons.url)
    with paused(settings, fake_cluster, slack, REPORT_STEP, draft()) as (c, tid):
        reject = slack_buttons(slack)["reject"]
        buttons.send(click("reject", reject["value"]))
        until(lambda: any(m == "views.open" for m, _, _ in slack.calls))
        meta = opened(slack)["private_metadata"]
        buttons.send(reject_submit(meta, "Never evict checkout: page the team."))
        wait_for(c, tid, "done")
        until(lambda: "teaching_approve" in posted(slack))
    assert rows(database_url, "select correction from teachings") == [
        (
            "The Operator rejected the proposed kubernetes_evict_pod, saying: "
            "Never evict checkout: page the team.",
        )
    ]


def test_a_reason_typed_on_the_console_drafts_too(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    slack = FakeSlack(buttons.url)
    with paused(settings, fake_cluster, slack, REPORT_STEP, draft()) as (c, tid):
        deadline = c.get(f"/investigations/{tid}", headers=AUTH).json()["deadline"]
        form = {"deadline": str(deadline), "approve": "0", "reason": "Page the team instead."}
        r = c.post(
            f"/console/investigations/{tid}/decision",
            data=form,
            headers=SAME,
            follow_redirects=False,
        )
        assert r.status_code == 303
        wait_for(c, tid, "done")
        until(lambda: "teaching_approve" in posted(slack))
    assert rows(database_url, "select correction from teachings") == [
        ("The Operator rejected the proposed kubernetes_evict_pod, saying: Page the team instead.",)
    ]


@pytest.mark.parametrize("message", [None, ""])
def test_no_reason_drafts_nothing(
    settings: Settings,
    fake_cluster: Any,
    buttons: FakeSocket,
    database_url: str,
    message: str | None,
) -> None:
    slack = FakeSlack(buttons.url)
    with client(
        settings,
        fake_cluster,
        EVICT,
        REPORT_STEP,
        actions=True,
        slack=slack.transport(),
        acme_channel=ACME,
    ) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "awaiting_approval")
        body = {"approve": False} | ({"message": message} if message is not None else {})
        assert c.post(f"/investigations/{tid}/decision", json=body, headers=AUTH).status_code == 202
        wait_for(c, tid, "done")
        until(lambda: "feedback_right" in posted(slack))
    assert len(Recording.sent) == 2  # the Triage and its resume: no draft
    assert rows(database_url, "select count(*) from teachings") == [(0,)]


def test_a_stale_rejection_drafts_nothing(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    settings.decision_timeout_seconds = 0
    slack = FakeSlack(buttons.url)
    with client(
        settings,
        fake_cluster,
        EVICT,
        REPORT_STEP,
        actions=True,
        slack=slack.transport(),
        acme_channel=ACME,
    ) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        until(lambda: "feedback_right" in posted(slack))
    assert rows(database_url, "select decided_by from decisions") == [("stale",)]
    assert len(Recording.sent) == 2
    assert rows(database_url, "select count(*) from teachings") == [(0,)]


# The console


def test_the_console_takes_feedback_and_reviews_teachings(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    slack = FakeSlack(buttons.url)
    with done(settings, fake_cluster, slack, draft()) as (c, tid):
        page = f"/console/investigations/{tid}"
        assert "Was this Report right?" in c.get(page, headers=VIEW).text
        bad = c.post(
            f"{page}/feedback",
            data={"correct": "0", "correction": " "},
            headers=SAME,
            follow_redirects=False,
        )
        assert bad.status_code == 400
        c.post(f"{page}/feedback", data={"correct": "1"}, headers=SAME, follow_redirects=False)
        wrong = {"correct": "0", "correction": CORRECTION}
        r = c.post(f"{page}/feedback", data=wrong, headers=SAME, follow_redirects=False)
        assert r.status_code == 303
        until(lambda: rows(database_url, "select status from teachings") == [("proposed",)])
        ((tid_,),) = rows(database_url, "select id from teachings")
        listing = c.get("/console/teachings?contract=acme", headers=VIEW).text
        assert LESSON.replace("'", "&#39;") in listing and CORRECTION in listing
        edited = "Ticket the platform team; never raise checkout's limit."
        r = c.post(
            f"/console/teachings/{tid_}/decision",
            data={"approve": "1", "text": edited},
            headers=SAME,
            follow_redirects=False,
        )
        assert r.status_code == 303
        again = c.post(
            f"/console/teachings/{tid_}/decision",
            data={"approve": "0"},
            headers=SAME,
            follow_redirects=False,
        )
        assert again.status_code == 409
        # Its Slack post shows the verdict and loses its buttons.
        ts = posted(slack)["teaching_approve"][0]
        until(lambda: any(m == "chat.update" and p["ts"] == ts for m, p, _ in slack.calls))
        assert (
            c.post(
                f"/console/teachings/{tid_}/retire", headers=SAME, follow_redirects=False
            ).status_code
            == 303
        )
        assert (
            c.post(
                f"/console/teachings/{tid_}/retire", headers=SAME, follow_redirects=False
            ).status_code
            == 409
        )
        written = {"contract": "acme", "text": "Check the CDN first.", "alerts": "A, B ,"}
        assert (
            c.post(
                "/console/teachings", data=written, headers=SAME, follow_redirects=False
            ).status_code
            == 303
        )
        too_long = {"contract": "acme", "text": "x" * 501}
        assert (
            c.post(
                "/console/teachings", data=too_long, headers=SAME, follow_redirects=False
            ).status_code
            == 400
        )
        assert (
            c.post(
                "/console/teachings", data={"contract": "nope", "text": "x"}, headers=SAME
            ).status_code
            == 400
        )
    assert rows(
        database_url, "select text, status, alerts, decided_by from teachings order by id"
    ) == [
        (edited, "retired", ["KubePodCrashLooping"], f"console:{LOGIN}"),
        ("Check the CDN first.", "approved", ["A", "B"], f"console:{LOGIN}"),
    ]
    assert rows(database_url, "select correct from feedback order by id") == [(True,), (False,)]


def test_console_feedback_is_for_a_finished_triage_only(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket
) -> None:
    slack = FakeSlack(buttons.url)
    with client(
        settings, fake_cluster, EVICT, actions=True, slack=slack.transport(), acme_channel=ACME
    ) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "awaiting_approval")
        r = c.post(f"/console/investigations/{tid}/feedback", data={"correct": "1"}, headers=SAME)
        assert r.status_code == 409


def test_another_contracts_teaching_is_never_decided_from_this_thread(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    """A Slack click names its thread's Investigation: a Teaching of another Contract
    (or another thread) can't be decided through it."""
    slack = FakeSlack(buttons.url)
    with done(settings, fake_cluster, slack, more=bank()) as (c, tid):
        theirs = c.post(BANK_URL, json=ALERT, headers=BANK_HOOK).json()["investigation"]
        with psycopg.connect(database_url) as conn:
            conn.execute(
                "insert into teachings (id, contract_id, text, status, source_id, proposed_at) "
                "values (7, 'bank', 'A bank lesson.', 'proposed', %s, 0), "
                "(8, 'acme', 'Another thread.', 'proposed', null, 0)",
                (theirs,),
            )
        for teaching in (7, 8):
            buttons.send(click("teaching_approve", json.dumps({"id": tid, "teaching": teaching})))
        until(lambda: ephemerals(slack) == [(OPERATOR, GONE)] * 2)
    assert rows(database_url, "select status from teachings order by id") == [
        ("proposed",),
        ("proposed",),
    ]


# Part b: approved Teachings in the prompts


def taught_row(i: int, text: str, alerts: list[str] | None = None) -> dict[str, Any]:
    return {"id": i, "text": text, "alerts": alerts or []}


def test_a_triage_gets_its_alerts_teachings_first_then_the_general_ones() -> None:
    rows = [
        taught_row(1, "old general"),
        taught_row(2, "for crash loops", ["KubePodCrashLooping"]),
        taught_row(3, "for another alert", ["DiskFull"]),
        taught_row(4, "new general"),
    ]
    text, left = teachings.section(rows, {"KubePodCrashLooping"})
    assert text.splitlines()[0].startswith("Teachings from the Operator")
    assert text.splitlines()[-3:] == [
        "- for crash loops (for KubePodCrashLooping)",
        "- new general",
        "- old general",
    ]
    assert left == 0 and "another alert" not in text
    everything, _ = teachings.section(rows, None)  # a Question
    assert "for another alert" in everything and everything.count("\n- ") == 4
    assert teachings.section([], {"X"}) == ("", 0)


def test_the_prompt_holds_at_most_30_and_6000_characters_newest_first() -> None:
    many = [taught_row(i, f"lesson {i}") for i in range(1, 36)]
    text, left = teachings.section(many, set())
    assert left == 5 and "- lesson 35" in text and "- lesson 6\n" in text + "\n"
    assert "- lesson 5\n" not in text + "\n"
    long = [taught_row(i, "x" * 480) for i in range(1, 15)]
    text, left = teachings.section(long, set())
    assert len(text) < teachings.MAX_PROMPT_CHARS + 200 and left == 2


def system_prompts() -> list[str]:
    return [str(m[0].content) for m in Recording.sent if m and m[0].type == "system"]


def migrated(database_url: str) -> None:
    """The Hub migrates when it starts; these tests write before that."""

    async def go() -> None:
        async with connect(database_url) as pool:
            await Store(pool).migrate()

    asyncio.run(go())


def seed(database_url: str) -> None:
    migrated(database_url)
    with psycopg.connect(database_url) as conn:
        for contract, status, text, alerts in [
            ("acme", "approved", "ACME-GENERAL lesson", []),
            ("acme", "approved", "ACME-CRASHLOOP lesson", ["KubePodCrashLooping"]),
            ("acme", "approved", "ACME-OTHER-ALERT lesson", ["DiskFull"]),
            ("acme", "proposed", "ACME-PROPOSED lesson", []),
            ("acme", "rejected", "ACME-REJECTED lesson", []),
            ("acme", "retired", "ACME-RETIRED lesson", []),
            ("bank", "approved", "BANK-APPROVED lesson", []),
        ]:
            conn.execute(
                "insert into teachings (contract_id, text, alerts, status, proposed_at) "
                "values (%s, %s, %s, %s, 0)",
                (contract, text, json.dumps(alerts), status),
            )


NEVER = ("ACME-PROPOSED", "ACME-REJECTED", "ACME-RETIRED", "BANK-APPROVED")


def test_only_the_contracts_approved_teachings_reach_a_triage(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    slack = FakeSlack(buttons.url)
    seed(database_url)
    alert = {**ALERT, "commonLabels": {"alertname": "KubePodCrashLooping", "namespace": "shop"}}
    alert["alerts"] = [{**ALERT["alerts"][0], "labels": {"alertname": "KubePodCrashLooping"}}]
    with client(
        settings, fake_cluster, REPORT_STEP, slack=slack.transport(), acme_channel=ACME, more=bank()
    ) as c:
        tid = c.post(URL, json=alert, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
    (prompt,) = system_prompts()
    assert prompt.index("ACME-CRASHLOOP") < prompt.index("ACME-GENERAL")
    assert "ACME-OTHER-ALERT" not in prompt
    for never in NEVER:
        assert never not in prompt, never


def test_a_question_gets_every_approved_teaching(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    seed(database_url)
    answer = call("Answer", "a1", answer="It's fine.", evidence=[REPORT["evidence"][0]])
    with client(settings, fake_cluster, answer, more=bank()) as c:
        r = c.post("/console/questions", data={"contract": "acme", "question": "OK?"}, headers=SAME)
        assert r.status_code == 200
        until(lambda: len(Recording.sent) == 1)
    (prompt,) = system_prompts()
    for shown in ("ACME-GENERAL", "ACME-CRASHLOOP", "ACME-OTHER-ALERT"):
        assert shown in prompt
    for never in NEVER:
        assert never not in prompt, never


def test_a_resumed_run_reads_the_teachings_as_they_are_then(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    """One retired while it waited is gone; one approved since is there."""
    slack = FakeSlack(buttons.url)
    seed(database_url)
    with paused(settings, fake_cluster, slack, REPORT_STEP) as (c, tid):
        with psycopg.connect(database_url) as conn:
            conn.execute("update teachings set status = 'retired' where text like 'ACME-GENERAL%'")
            conn.execute(
                "insert into teachings (contract_id, text, status, proposed_at) "
                "values ('acme', 'ACME-NEW lesson', 'approved', 0)"
            )
        c.post(f"/investigations/{tid}/decision", json={"approve": True}, headers=AUTH)
        wait_for(c, tid, "done")
    first, resumed = system_prompts()
    assert "ACME-GENERAL" in first and "ACME-NEW" not in first
    assert "ACME-GENERAL" not in resumed and "ACME-NEW" in resumed


def test_the_console_warns_when_teachings_dont_fit(
    settings: Settings, fake_cluster: Any, buttons: FakeSocket, database_url: str
) -> None:
    migrated(database_url)
    with psycopg.connect(database_url) as conn:
        for i in range(31):
            conn.execute(
                "insert into teachings (contract_id, text, status, proposed_at) "
                "values ('acme', %s, 'approved', 0)",
                (f"lesson {i}",),
            )
    with client(settings, fake_cluster) as c:
        page = c.get("/console/teachings", headers=VIEW).text
    assert "<code>acme</code>: 1 approved Teaching(s) don't fit in a prompt" in page
