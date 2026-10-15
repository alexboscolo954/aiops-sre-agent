"""The Hub restarts: what survives, what is never replayed, what goes Stale.

Each test runs two Hub instances, one after the other, on the same database.
"""

import asyncio
import threading
import time
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from aiops_agent import agent
from aiops_agent.api import create_app
from aiops_agent.config import Settings
from aiops_agent.models import Investigation
from aiops_agent.store import Store, connect, now
from tests.conftest import REPORT, call, make_contract, scripted
from tests.test_api import ALERT, AUTH, HOOK, URL, client

EVICT = call(
    "kubernetes_evict_pod", "c1", cluster="test", namespace="shop", name="checkout-7d9f-abc"
)
REPORT_STEP = call("TriageReport", "c2", **REPORT)


@pytest.fixture(autouse=True)
def _database(settings: Settings, database_url: str) -> None:
    settings.database_url = SecretStr(database_url)


def wait_for(c: TestClient, tid: str, status: str, seconds: float = 3) -> dict[str, Any]:
    end = time.monotonic() + seconds
    while True:
        t: dict[str, Any] = c.get(f"/investigations/{tid}", headers=AUTH).json()
        if t["status"] == status or time.monotonic() > end:
            assert t["status"] == status, t
            return t
        time.sleep(0.02)


def paused(settings: Settings, fake_cluster: Any) -> str:
    """Start a Hub, let it pause on an eviction, stop it. Returns the Investigation id."""
    with client(settings, fake_cluster, EVICT, actions=True) as c:
        tid: str = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "awaiting_approval")
    return tid


def decisions(database_url: str, tid: str) -> list[tuple[bool, str]]:
    with psycopg.connect(database_url) as conn:
        rows = conn.execute(
            "select approve, decided_by from decisions where investigation_id = %s order by id",
            (tid,),
        ).fetchall()
    return [(r[0], r[1]) for r in rows]


def test_pending_approval_survives_a_restart(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    tid = paused(settings, fake_cluster)
    with client(settings, fake_cluster, REPORT_STEP, actions=True) as c:
        assert wait_for(c, tid, "awaiting_approval")["pending"][0]["name"] == "kubernetes_evict_pod"
        assert c.post(f"/investigations/{tid}/decision", json={"approve": True}, headers=AUTH)
        assert len(wait_for(c, tid, "done")["executed_actions"]) == 1
    fake_cluster[0].create_namespaced_pod_eviction.assert_called_once()
    assert decisions(database_url, tid) == [(True, "operator")]


def test_a_run_cut_off_by_a_restart_is_failed_never_replayed(
    settings: Settings, fake_cluster: Any
) -> None:
    started = threading.Event()

    def slow_eviction(*args: Any, **kwargs: Any) -> None:
        started.set()
        time.sleep(1)  # the Hub stops while the approved write is in flight

    fake_cluster[0].create_namespaced_pod_eviction.side_effect = slow_eviction
    with client(settings, fake_cluster, EVICT, REPORT_STEP, actions=True) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "awaiting_approval")
        c.post(f"/investigations/{tid}/decision", json={"approve": True}, headers=AUTH)
        assert started.wait(5)
    with client(settings, fake_cluster, REPORT_STEP, actions=True) as c:
        t = wait_for(c, tid, "failed")
    assert "not resumed, so nothing runs twice" in t["error"]
    assert "(kubernetes_evict_pod) may or may not have run" in t["error"]
    assert fake_cluster[0].create_namespaced_pod_eviction.call_count == 1


def test_deadline_still_ahead_is_rearmed(settings: Settings, fake_cluster: Any) -> None:
    settings.decision_timeout_seconds = 2
    tid = paused(settings, fake_cluster)
    with client(settings, fake_cluster, REPORT_STEP, actions=True) as c:
        assert c.get(f"/investigations/{tid}", headers=AUTH).json()["status"] == "awaiting_approval"
        assert wait_for(c, tid, "done", seconds=5)["executed_actions"] == []
    fake_cluster[0].create_namespaced_pod_eviction.assert_not_called()


def test_deadline_passed_while_down_goes_stale_at_startup(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    settings.decision_timeout_seconds = 1
    tid = paused(settings, fake_cluster)
    time.sleep(1.1)
    settings.decision_timeout_seconds = 3600  # the new Hub keeps the stored deadline
    with client(settings, fake_cluster, REPORT_STEP, actions=True) as c:
        wait_for(c, tid, "done", seconds=1)
    assert decisions(database_url, tid) == [(False, "stale")]


def test_group_resolved_while_paused_goes_stale_at_startup(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    tid = paused(settings, fake_cluster)
    with psycopg.connect(database_url) as conn:
        conn.execute("update investigations set group_resolved = true where id = %s", (tid,))
    with client(settings, fake_cluster, REPORT_STEP, actions=True) as c:
        wait_for(c, tid, "done")
    assert decisions(database_url, tid) == [(False, "stale")]
    fake_cluster[0].create_namespaced_pod_eviction.assert_not_called()


def test_investigation_of_a_removed_contract_is_failed(
    settings: Settings, fake_cluster: Any
) -> None:
    tid = paused(settings, fake_cluster)
    other = make_contract(contract_id="bank", webhook_token="bank-token")

    def mcp(c: Any) -> agent.Toolbox:
        return agent.build_mcp(c, settings, {"test": fake_cluster})

    with TestClient(create_app(settings, scripted(), mcp, {"bank": other})) as c:
        t = wait_for(c, tid, "failed")
    assert t["error"] == "Contract 'acme' is no longer configured"


@pytest.mark.anyio
async def test_only_one_decision_claims_a_pause(database_url: str) -> None:
    async with connect(database_url) as pool:
        store = Store(pool)
        await store.migrate()
        deadline = now() + 60
        t = Investigation(
            id="i1",
            contract_id="acme",
            title="t",
            started=now(),
            status="awaiting_approval",
            pending=[{"name": "kubernetes_evict_pod"}],
            deadline=deadline,
        )
        await store.insert(t)
        claims = await asyncio.gather(*(store.claim("i1", deadline) for _ in range(5)))
        assert [c for c in claims if c is not None] == [[{"name": "kubernetes_evict_pod"}]]
        assert await store.claim("i1", deadline) is None
        # A claim for an older pause of the same Investigation never matches.
        t.status, t.deadline = "awaiting_approval", deadline + 10
        await store.save(t)
        assert await store.claim("i1", deadline) is None
