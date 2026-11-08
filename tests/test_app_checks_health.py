"""Checks, Deploy verifications and Health in the console app's API (slice 11.6b): each
the Contract's own, Health checked now through its own tools, its secrets by name only."""

import asyncio
import json
from typing import Any

import psycopg
from fastapi.testclient import TestClient
from kubernetes.client import ApiException
from pydantic import SecretStr

from aiops_agent import agent, contracts
from aiops_agent.api import create_app
from aiops_agent.config import Settings
from aiops_agent.models import CheckResult, Evidence, Investigation, TriageReport
from aiops_agent.store import Store, connect
from tests.conftest import REPORT, call, make_contract, make_fake_cluster, scripted
from tests.test_api import ALERT, HOOK, URL, client
from tests.test_console import AS_OPERATOR, OPERATOR, VIEW
from tests.test_cost import HAIKU
from tests.test_restart import wait_for


def seed(database_url: str) -> None:
    """acme: a Check failing since its last Run, one skipped and never run, and two
    Deploy verifications (one started, one skipped); bank: one of each."""

    async def go() -> None:
        async with connect(database_url) as pool:
            st = Store(pool)
            await st.migrate()
            ev = [Evidence(source="http_get", finding="503")]
            report = TriageReport.model_validate(REPORT)
            bad = CheckResult(passed=False, summary="down", evidence=ev, report=report)
            run = Investigation(
                id="r1", kind="check", contract_id="acme", title="api answers", started=50,
                status="done", check_result=bad,
            )  # fmt: skip
            await st.insert(run)
            await st.save(run)

    asyncio.run(go())
    changes = json.dumps([{"namespace": "shop", "object": "Deployment/api", "revision": "4"}])
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "insert into check_schedules values "
            "('acme', 'api answers', '*/5 * * * * UTC', 100, 'r1', 'r1', null, null), "
            "('acme', 'backups', '0 3 * * * UTC', 200, null, null, 90, 'over budget'), "
            "('bank', 'theirs', '0 * * * * UTC', 300, null, null, null, null)"
        )
        conn.execute(
            "insert into deploy_checks (contract_id, cluster, namespace, state, first_seen, "
            "due, changes, investigation_id, skipped_reason) values "
            "('acme', 'test', 'shop', 'started', 1, 10, %s, 'r1', null), "
            "('acme', 'test', 'shop', 'skipped', 2, 20, %s, null, 'Kill switch on'), "
            "('bank', 'test', 'bank', 'pending', 3, 30, %s, null, null)",
            (changes, changes, changes),
        )


def test_a_contracts_checks_and_deploy_verifications_are_its_own(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    from tests.test_app_investigations import hub

    with hub(settings, fake_cluster, database_url) as c:
        seed(database_url)
        acme = c.get("/api/v1/contracts/acme/checks", headers=VIEW).json()
        bank = c.get("/api/v1/contracts/bank/checks", headers=VIEW).json()
        unknown = c.get("/api/v1/contracts/nope/checks", headers=VIEW).status_code
        no_cookie = c.get("/api/v1/contracts/acme/checks", headers=AS_OPERATOR).status_code
    failing, skipped = acme["checks"]
    assert (failing["name"], failing["last_id"], failing["failing_id"]) == (
        "api answers",
        "r1",
        "r1",
    )
    assert (failing["last_status"], failing["last_passed"], failing["last_started"]) == (
        "done",
        False,
        50,
    )
    assert (skipped["last_id"], skipped["skipped_at"], skipped["skipped_reason"]) == (
        None,
        90,
        "over budget",
    )
    assert [(d["state"], d["passed"], d["skipped_reason"]) for d in acme["deploys"]] == [
        ("skipped", None, "Kill switch on"),  # newest first
        ("started", False, None),
    ]
    assert acme["deploys"][1]["changes"][0]["object"] == "Deployment/api"
    assert [k["name"] for k in bank["checks"]] == ["theirs"]
    assert [d["namespace"] for d in bank["deploys"]] == ["bank"]
    assert unknown == 404 and no_cookie == 401


def test_health_checks_only_the_contract_asked_for_now(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    settings.model_prices = {settings.model: HAIKU}  # a budget needs its model priced
    # A key in a plain string setting: redacted on the page as on the Jinja one.
    settings.console_url = "https://hub.example/?token=abcdefghijklmnop5678"
    broken = make_fake_cluster()
    broken[1].list_namespaced_deployment.side_effect = ApiException(
        403, "Forbidden token=abcdefghijklmnop1234"
    )
    bank = make_contract(contract_id="bank", webhook_token="bank-token", monthly_budget_usd=20)
    with client(
        settings, fake_cluster, call("TriageReport", "r1", **REPORT), more={"bank": (bank, broken)}
    ) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")

        async def spend() -> None:
            async with connect(database_url) as pool:
                await Store(pool).record_usage(None, "bank", "m", 1, 1, 0.25)

        asyncio.run(spend())
        broken[1].list_namespaced_deployment.reset_mock()
        acme = c.get("/api/v1/contracts/acme/health", headers=VIEW)
        asked_acme = broken[1].list_namespaced_deployment.call_count
        theirs = c.get("/api/v1/contracts/bank/health", headers=VIEW)
        unknown = c.get("/api/v1/contracts/nope/health", headers=VIEW).status_code
        no_cookie = c.get("/api/v1/contracts/acme/health", headers=AS_OPERATOR).status_code
    mine, other = acme.json(), theirs.json()
    assert [(p["name"], p["ok"]) for p in mine["integrations"]] == [("kubernetes test", True)]
    assert asked_acme == 0  # bank's cluster isn't probed for acme's page
    assert mine["last"]["id"] == tid and other["last"] is None
    assert [(p["name"], p["ok"]) for p in other["integrations"]] == [("kubernetes test", False)]
    assert "Kubernetes API 403" in other["integrations"][0]["detail"]
    assert "abcdefghijklmnop1234" not in theirs.text  # a check's error is redacted
    assert mine["budget_usd"] is None
    assert (other["spent_usd"], other["budget_usd"]) == (0.25, 20)
    assert "id: bank" in other["config"] and "id: acme" not in other["config"]
    assert "approver-token" not in acme.text and "**********" in mine["hub"]
    assert "abcdefghijklmnop5678" not in acme.text and "hub.example" in mine["hub"]
    assert unknown == 404 and no_cookie == 401


def test_health_names_secrets_without_their_values_and_fails_unbuildable_tools(
    settings: Settings, fake_cluster: Any, database_url: str, two_contracts: Any
) -> None:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    settings.approver_token = SecretStr("approver-token")
    shop: contracts.Contract = two_contracts["demo-shop"]
    secret = shop.secret("prometheus-token").get_secret_value()

    def mcp(c: contracts.Contract) -> agent.Toolbox:
        if c.id == "demo-bank":
            raise RuntimeError("kubeconfig not found: token=abcdefghijklmnop1234")
        return agent.build_mcp(c, settings, {cl.name: fake_cluster for cl in c.clusters})

    with TestClient(create_app(settings, scripted(), mcp, two_contracts)) as c:
        shown = c.get("/api/v1/contracts/demo-shop/health", headers=VIEW)
        bank = c.get("/api/v1/contracts/demo-bank/health", headers=VIEW)
    assert secret not in shown.text
    assert shown.json()["secrets"]["prometheus-token"] is True
    (tools,) = bank.json()["integrations"]
    assert (tools["name"], tools["ok"]) == ("tools", False)
    assert "RuntimeError: kubeconfig not found" in tools["detail"]
    assert "abcdefghijklmnop1234" not in bank.text
