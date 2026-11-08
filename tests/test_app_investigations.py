"""Investigations in the console app's API (slice 11.5a): a Contract's list, one in full
with its Report as fields, the Scenario download and the token page's call, behind the
same doors as the rest of /api/v1."""

import asyncio
from typing import Any

from pydantic import SecretStr

from aiops_agent.config import Settings
from aiops_agent.console import COOKIE, action_key
from aiops_agent.models import AlertGroup, CheckResult, Evidence, Investigation, TriageReport
from aiops_agent.store import Store, connect
from tests.conftest import REPORT, call, make_contract
from tests.test_api import ALERT, HOOK, URL, client
from tests.test_console import AS_OPERATOR, OPERATOR, VIEW
from tests.test_restart import wait_for


def hub(settings: Settings, fake_cluster: Any, database_url: str, *steps: Any) -> Any:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    bank = make_contract(contract_id="bank")
    return client(settings, fake_cluster, *steps, more={"bank": (bank, fake_cluster)})


def seed(database_url: str) -> None:
    """acme's paused Triage with everything a page shows, a passing and a failing Check,
    and bank's own Triage. Seeded once the Hub is up: at startup it resumes what it
    finds unfinished."""

    async def go() -> None:
        async with connect(database_url) as pool:
            st = Store(pool)
            await st.migrate()
            report = TriageReport.model_validate(REPORT)
            ev = [Evidence(source="kubernetes_list_pods", finding="<b>restarts</b>")]
            t1 = Investigation(
                id="t1", contract_id="acme", title="<script>x</script>", started=100,
                status="awaiting_approval", deadline=200.5, report=report,
                pending=[{"name": "kubernetes_evict_pod", "description": "evict shop/p"}],
                executed_actions=["kubernetes_scale_deployment"],
                input={"alert": ALERT},  # recorded, but a paused Run saves no Scenario
            )  # fmt: skip
            await st.insert(t1)
            await st.save(t1)  # insert writes a new Run; the pause and Report come with save
            await st.record_tool_call(
                "t1", "acme", "kubernetes_list_pods", {"n": 1}, "x" * 5000, False
            )
            await st.record_decision(
                "t1", False, [{"name": "kubernetes_evict_pod"}], "no", "slack:U1"
            )
            await st.record_usage("t1", "acme", "m", 10, 5, 0.0012)
            await st.record_masked("t1", "acme", ["<name-0a1b2c3d>", "<ip-0a1b2c3d>"])
            group = AlertGroup.model_validate({**ALERT, "groupKey": "g2"})
            await st.add_related("t1", "acme", group, {"namespace": "shop"}, True, 150)
            ok = CheckResult(passed=True, summary="fine", evidence=ev)
            bad = CheckResult(passed=False, summary="down", evidence=ev, report=report)
            for iid, verdict, at in (("ok", ok, 300), ("bad", bad, 400)):
                check = Investigation(
                    id=iid, kind="check", contract_id="acme", title=iid, started=at,
                    status="done", check_result=verdict,
                )  # fmt: skip
                await st.insert(check)
                await st.save(check)
            await st.add_teaching("acme", "taught by t1", [], source_id="t1")
            await st.add_teaching("acme", "taught by another", [], source_id="bad")
            await st.add_feedback(t1, False, "wrong pod", "console:op")
            gone = Investigation(
                id="g1", contract_id="gone", title="its Contract is gone", started=1
            )
            await st.insert(gone)
            theirs = Investigation(id="b1", contract_id="bank", title="theirs", started=500)
            await st.insert(theirs)
            await st.save(theirs.model_copy(update={"status": "done"}))

    asyncio.run(go())


def test_a_contracts_list_is_its_own_newest_first_without_passing_checks(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    with hub(settings, fake_cluster, database_url) as c:
        seed(database_url)
        acme = c.get("/api/v1/contracts/acme/investigations", headers=VIEW).json()
        bank = c.get("/api/v1/contracts/bank/investigations", headers=VIEW).json()
        unknown = c.get("/api/v1/contracts/nope/investigations", headers=VIEW).status_code
        no_cookie = c.get("/api/v1/contracts/acme/investigations", headers=AS_OPERATOR)
    assert [(t["id"], t["status"], t["failed"]) for t in acme] == [
        ("bad", "done", True),
        ("t1", "awaiting_approval", False),
    ]
    assert [t["id"] for t in bank] == ["b1"]
    assert unknown == 404
    assert no_cookie.status_code == 401
    assert no_cookie.json()["detail"]["token_url"] == "/app/?view=token"


def test_one_investigation_in_full_with_its_report_as_fields(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    with hub(settings, fake_cluster, database_url) as c:
        seed(database_url)
        t = c.get("/api/v1/investigations/t1", headers=VIEW).json()
        theirs = c.get("/api/v1/investigations/b1", headers=VIEW).json()
        unknown = c.get("/api/v1/investigations/nope", headers=VIEW).status_code
        gone = c.get("/api/v1/investigations/g1", headers=VIEW).status_code
    assert t["title"] == "<script>x</script>"  # as stored: the app renders it as text
    assert t["report"]["category"] == REPORT["category"]
    assert t["report"]["evidence"] == [
        {"source": e["source"], "finding": e["finding"], "link": None} for e in REPORT["evidence"]
    ]
    assert t["pending"] == ["evict shop/p"] and t["deadline"] == 200.5
    assert t["executed_actions"] == ["kubernetes_scale_deployment"]
    assert t["usage"] == {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.0012}
    assert t["masked"] == {"name": 1, "ip": 1}
    assert [(d["approve"], d["actions"], d["message"]) for d in t["decisions"]] == [
        (False, ["kubernetes_evict_pod"], "no")
    ]
    assert t["related"][0]["matched"] == {"namespace": "shop"} and t["related"][0]["louder"]
    (tool,) = t["tool_calls"]
    assert tool["tool"] == "kubernetes_list_pods" and len(tool["result"]) == 4000
    assert t["scenario"] is False  # its input is recorded, but it isn't finished
    assert theirs["contract"] == "bank"  # each Investigation is shown with its own Contract
    assert unknown == gone == 404  # a Contract no longer loaded shows nothing
    assert [x["text"] for x in t["taught"]] == ["taught by t1"]
    assert [(f["correct"], f["correction"]) for f in t["feedback"]] == [(False, "wrong pod")]


def test_a_finished_triage_downloads_the_same_scenario_as_the_older_page(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    report = call("TriageReport", "r", **REPORT)
    with hub(settings, fake_cluster, database_url, report) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        shown = c.get(f"/api/v1/investigations/{tid}", headers=VIEW).json()
        new = c.get(f"/api/v1/investigations/{tid}/scenario.yaml", headers=VIEW)
        old = c.get(f"/console/investigations/{tid}/scenario.yaml", headers=VIEW)
        no_cookie = c.get(f"/api/v1/investigations/{tid}/scenario.yaml", headers=AS_OPERATOR)
    assert shown["scenario"] is True
    assert new.status_code == 200 and new.text == old.text
    assert new.headers["content-disposition"] == old.headers["content-disposition"]
    assert no_cookie.status_code == 401


def test_the_token_call_sets_the_cookie_from_the_apps_own_page_only(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    with hub(settings, fake_cluster, database_url) as c:
        same = {**AS_OPERATOR, "Sec-Fetch-Site": "same-origin"}
        wrong = c.post("/api/v1/token", json={"token": "nope"}, headers=same)
        cross = c.post(
            "/api/v1/token",
            json={"token": "approver-token"},
            headers={**AS_OPERATOR, "Sec-Fetch-Site": "cross-site"},
        )
        stranger = c.post(
            "/api/v1/token",
            json={"token": "approver-token"},
            headers={"Sec-Fetch-Site": "same-origin"},
        )
        ok = c.post("/api/v1/token", json={"token": "approver-token"}, headers=same)
    assert [wrong.status_code, cross.status_code, stranger.status_code] == [403, 403, 403]
    assert "set-cookie" not in wrong.headers
    assert ok.status_code == 204
    cookie = ok.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}={action_key('approver-token')};")
    assert "approver-token" not in cookie
    for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/;"):
        assert flag in cookie, flag
