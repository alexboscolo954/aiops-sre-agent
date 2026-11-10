"""The Kill switch (slice 11.2a): while a Contract's is on, approving is refused on
every path and the pause kept (rejecting still works); a change approved just before it
went on is refused where it would run; another Contract's changes still run; only the
console turns it off."""

from typing import Any

import psycopg
import pytest
from pydantic import SecretStr

from squero.api import KILLED
from squero.config import Settings
from squero.store import Store, connect
from tests.test_api import (
    ALERT,
    AUTH,
    BANK_HOOK,
    BANK_URL,
    EVICT_THEN_REPORT,
    HOOK,
    URL,
    bank,
    client,
    wait_for,
)
from tests.test_console import ACT, AS_OPERATOR, OPERATOR, SAME, VIEW
from tests.test_slack import (
    ANY_DECIDED,
    TOKEN,
    FakeSlack,
    FakeSocket,
    buttons,
    click,
    ephemerals,
    until,
)
from tests.test_slack import paused as slack_paused
from tests.test_slack import sock as sock


def turn_on(database_url: str, contract_id: str = "acme") -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "insert into kill_switches (contract_id, set_by, set_at) values (%s, 'test', 1)",
            (contract_id,),
        )


def evictions(fake: Any) -> int:
    return int(fake[0].create_namespaced_pod_eviction.call_count)


# --- the store ---------------------------------------------------------------------------


@pytest.fixture
async def store(database_url: str) -> Any:
    async with connect(database_url) as pool:
        s = Store(pool)
        await s.migrate()
        yield s


@pytest.mark.anyio
async def test_a_contracts_switch_is_its_own_and_the_first_who_stays(store: Store) -> None:
    assert await store.kill_switch("acme") is None
    assert await store.turn_on_kill_switch("acme", "mcp:alex", 10.0)
    assert not await store.turn_on_kill_switch("acme", "console:alex", 20.0)
    assert await store.kill_switch("acme") == {"set_by": "mcp:alex", "set_at": 10.0}
    assert await store.kill_switch("bank") is None
    assert await store.turn_off_kill_switch("acme")
    assert not await store.turn_off_kill_switch("acme")
    assert await store.kill_switch("acme") is None


# --- approving is refused, the pause kept; rejecting still works ---------------------------


def test_approving_is_refused_and_the_pause_kept_rejecting_still_works(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    settings.database_url = SecretStr(database_url)
    with client(settings, fake_cluster, *EVICT_THEN_REPORT, actions=True) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "awaiting_approval")
        turn_on(database_url)
        refused = c.post(f"/investigations/{tid}/decision", json={"approve": True}, headers=AUTH)
        still = wait_for(c, tid, "awaiting_approval")
        rejected = c.post(f"/investigations/{tid}/decision", json={"approve": False}, headers=AUTH)
        done = wait_for(c, tid, "done")
    assert (refused.status_code, refused.json()["detail"]) == (409, KILLED)
    assert still["pending"] and rejected.status_code == 202
    assert done["executed_actions"] == [] and evictions(fake_cluster) == 0


def test_the_app_refuses_an_approval_with_the_reason(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    with client(settings, fake_cluster, *EVICT_THEN_REPORT, actions=True) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        deadline = wait_for(c, tid, "awaiting_approval")["deadline"]
        turn_on(database_url)
        r = c.post(
            f"/api/v1/investigations/{tid}/decision",
            json={"deadline": deadline, "approve": True},
            headers=SAME,
        )
        assert wait_for(c, tid, "awaiting_approval")["pending"]
    assert r.status_code == 409 and r.json()["detail"] == KILLED
    assert evictions(fake_cluster) == 0


def test_the_slack_button_refuses_an_approval_with_the_reason(
    settings: Settings, fake_cluster: Any, sock: FakeSocket, database_url: str
) -> None:
    from tests.test_slack import OPERATOR as SLACK_OPERATOR

    settings.database_url = SecretStr(database_url)
    settings.slack_bot_token = SecretStr(TOKEN)
    slack = FakeSlack(sock.url)
    with slack_paused(settings, fake_cluster, slack) as (c, tid):
        turn_on(database_url)
        sock.send(click("approve", buttons(slack)["approve"]["value"]))
        until(lambda: ephemerals(slack) == [(SLACK_OPERATOR, KILLED)])
        assert wait_for(c, tid, "awaiting_approval")["pending"]
    assert KILLED != ANY_DECIDED and evictions(fake_cluster) == 0


# --- refused where it would run ----------------------------------------------------------


def test_a_change_approved_before_the_switch_went_on_is_refused_where_it_would_run(
    settings: Settings, fake_cluster: Any, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Off when the approval is claimed, on by the time the eviction would run."""
    settings.database_url = SecretStr(database_url)
    reads: list[str] = []
    original = Store.kill_switch

    async def racing(self: Store, contract_id: str) -> dict[str, Any] | None:
        reads.append(contract_id)
        if len(reads) == 1:
            return None
        return await original(self, contract_id) or {"set_by": "mcp:alex", "set_at": 1.0}

    with client(settings, fake_cluster, *EVICT_THEN_REPORT, actions=True) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "awaiting_approval")
        monkeypatch.setattr(Store, "kill_switch", racing)
        approved = c.post(f"/investigations/{tid}/decision", json={"approve": True}, headers=AUTH)
        done = wait_for(c, tid, "done")
    assert approved.status_code == 202 and len(reads) >= 2
    assert evictions(fake_cluster) == 0
    (executed,) = done["executed_actions"]
    assert executed.startswith("FAILED kubernetes_evict_pod") and "Kill switch is on" in executed


def test_another_contracts_switch_never_stops_this_ones_changes(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    settings.database_url = SecretStr(database_url)
    other = bank(actions=True)
    with client(settings, fake_cluster, *EVICT_THEN_REPORT, actions=True, more=other) as c:
        turn_on(database_url, "acme")
        tid = c.post(BANK_URL, json=ALERT, headers=BANK_HOOK).json()["investigation"]
        wait_for(c, tid, "awaiting_approval")
        approved = c.post(f"/investigations/{tid}/decision", json={"approve": True}, headers=AUTH)
        done = wait_for(c, tid, "done")
    assert approved.status_code == 202 and not done["executed_actions"][0].startswith("FAILED")
    assert evictions(other["bank"][1]) == 1


# --- the console's switch: on and off, only from its own pages ----------------------------


def test_the_console_turns_it_on_and_off_only_from_its_own_pages(
    settings: Settings, fake_cluster: Any, database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    path = "/api/v1/contracts/acme/kill-switch"
    same = {**VIEW, "Sec-Fetch-Site": "same-origin"}
    with client(settings, fake_cluster) as c, caplog.at_level("INFO", logger="squero.webapp"):
        off = c.get(path, headers=VIEW).json()
        refused = [
            c.post(path, headers={**VIEW, "Sec-Fetch-Site": "cross-site"}).status_code,
            c.post(path, headers={**AS_OPERATOR, "Sec-Fetch-Site": "same-origin"}).status_code,
            c.post(path, headers={**ACT, "Sec-Fetch-Site": "same-origin"}).status_code,
            c.delete(path, headers={**VIEW, "Sec-Fetch-Site": "cross-site"}).status_code,
        ]
        on = c.post(path, headers=same).json()
        again = c.post(path, headers=same).json()
        cleared = c.delete(path, headers=same).json()
        unknown = c.post("/api/v1/contracts/nope/kill-switch", headers=same).status_code
    assert off == {"on": False, "by": None, "since": None}
    assert refused == [403, 401, 403, 403]
    assert on["on"] and on["by"] == f"console:{OPERATOR}" and again == on
    assert cleared == {"on": False, "by": None, "since": None} and unknown == 404
    logged = [r.message for r in caplog.records if r.name == "squero.webapp"]
    assert logged == [
        f"kill switch acme on by console:{OPERATOR}",
        f"kill switch acme off by console:{OPERATOR}",
    ]


def test_reads_still_run_while_it_is_on(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    """Only what the approval gate covers is refused: a Triage still investigates."""
    from tests.conftest import REPORT, call

    settings.database_url = SecretStr(database_url)
    steps = [
        call("kubernetes_list_pods", "c1", cluster="test", namespace="shop"),
        call("TriageReport", "c2", **REPORT),
    ]
    with client(settings, fake_cluster, *steps, actions=True) as c:
        turn_on(database_url)
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
    with psycopg.connect(database_url) as conn:
        (row,) = conn.execute("select tool, is_error, result from tool_calls").fetchall()
    assert row[0] == "kubernetes_list_pods" and not row[1] and "Kill switch" not in row[2]
