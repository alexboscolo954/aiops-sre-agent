"""The console's doors, on the JSON API the console app uses: only an Operator's
Tailscale identity gets in, changes need the approver cookie and a same-origin request,
and what a page shows is each Contract's own."""

from typing import Any

from pydantic import SecretStr

from aiops_agent import agent
from aiops_agent.config import Settings
from aiops_agent.console import COOKIE, action_key
from tests.conftest import REPORT, call, make_contract, make_fake_cluster
from tests.test_api import ALERT, AUTH, BANK_HOOK, BANK_URL, HOOK, URL, client
from tests.test_restart import wait_for

OPERATOR = "alex@example.com"
AS_OPERATOR = {"Tailscale-User-Login": OPERATOR, "Tailscale-User-Name": "Alex"}
ACT = {"Cookie": f"{COOKIE}={action_key('approver-token')}"}
VIEW = {**AS_OPERATOR, **ACT}  # the identity, and this browser has the token
SAME = {**VIEW, "Origin": "http://testserver"}
CSP = "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'"


def test_only_a_listed_tailscale_login_gets_in(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    with client(settings, fake_cluster) as c:
        refused = [
            c.get("/api/v1/contracts", headers=ACT),
            c.get("/api/v1/contracts", headers={"Tailscale-User-Login": "", **ACT}),
            c.get(
                "/api/v1/contracts", headers={"Tailscale-User-Login": "mallory@x.example", **ACT}
            ),
            c.get(
                "/api/v1/contracts", headers={**AUTH, **ACT}
            ),  # the approver token is not a login
        ]
        # The identity alone opens only the token call: a forged header sees nothing.
        no_token = c.get("/api/v1/contracts", headers=AS_OPERATOR)
        bad_token = c.get("/api/v1/contracts", headers={**AS_OPERATOR, "Cookie": f"{COOKIE}=x"})
        ok = c.get("/api/v1/contracts", headers=VIEW)
        api = c.get("/investigations", headers={"Tailscale-User-Login": OPERATOR})
    assert [r.status_code for r in refused] == [403] * 4
    for r in (no_token, bad_token):
        assert r.status_code == 401
        assert r.json()["detail"]["token_url"] == "/app/?view=token"
    assert ok.status_code == 200 and "acme" in [x["id"] for x in ok.json()]
    assert ok.headers["content-security-policy"] == CSP
    assert ok.headers["x-frame-options"] == "DENY"
    assert api.status_code in {401, 403}  # the Hub's API still wants the approver token


# Investigations: list per Contract, detail; acting needs the token and same origin.


EVICT = call(
    "kubernetes_evict_pod", "c1", cluster="test", namespace="shop", name="checkout-7d9f-abc"
)


def test_investigations_are_listed_per_contract_and_shown(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    bank = make_contract(contract_id="bank", webhook_token="bank-token")
    steps = [
        call("kubernetes_list_pods", "l1", cluster="test", namespace="shop"),
        call("TriageReport", "r1", **REPORT),
        call("TriageReport", "r2", **{**REPORT, "summary": "bank's own summary"}),
    ]
    with client(settings, fake_cluster, *steps, more={"bank": (bank, make_fake_cluster())}) as c:
        a = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, a, "done")
        b = c.post(BANK_URL, json=ALERT, headers=BANK_HOOK).json()["investigation"]
        wait_for(c, b, "done")
        acme = [
            t["id"] for t in c.get("/api/v1/contracts/acme/investigations", headers=VIEW).json()
        ]
        only_bank = [
            t["id"] for t in c.get("/api/v1/contracts/bank/investigations", headers=VIEW).json()
        ]
        unknown = c.get("/api/v1/contracts/nope/investigations", headers=VIEW)
        detail = c.get(f"/api/v1/investigations/{a}", headers=VIEW)
        missing = c.get("/api/v1/investigations/nope", headers=VIEW)
        anonymous = c.get(f"/api/v1/investigations/{a}", headers=ACT)
    assert a in acme and b not in acme and b in only_bank and a not in only_bank
    assert unknown.status_code == 404
    assert detail.status_code == 200 and detail.headers["x-frame-options"] == "DENY"
    shown = detail.json()
    assert shown["report"]["summary"] == REPORT["summary"]
    assert "bank's own summary" not in detail.text
    assert any(t["tool"] == "kubernetes_list_pods" for t in shown["tool_calls"])
    assert missing.status_code == 404 and anonymous.status_code == 403


def test_acting_needs_the_token_cookie_and_a_same_origin_post(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    report = call("TriageReport", "r1", **REPORT)
    with client(settings, fake_cluster, EVICT, report, actions=True) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        t = wait_for(c, tid, "awaiting_approval")
        assert t["pending"] and t["deadline"] is not None
        url = f"/api/v1/investigations/{tid}/decision"
        body: dict[str, Any] = {"approve": True, "deadline": t["deadline"]}

        def post(headers: dict[str, str]) -> int:
            return c.post(url, json=body, headers=headers).status_code

        origin = {"Origin": "http://testserver"}
        assert post({**AS_OPERATOR, **origin}) == 401  # no token: the token call first
        not_key = {"Cookie": f"{COOKIE}=approver-token"}  # the token itself isn't the key
        assert post({**AS_OPERATOR, **origin, **not_key}) == 401
        assert post({**VIEW, "Sec-Fetch-Site": "cross-site"}) == 403
        assert post({**VIEW, "Origin": "https://evil.example"}) == 403
        assert post(VIEW) == 403  # neither Sec-Fetch-Site nor Origin
        assert post({**ACT, **origin}) == 403  # no identity
        body["deadline"] = 1.0  # another pause
        assert post(SAME) == 409
        body["deadline"] = t["deadline"]
        assert post({**VIEW, "Sec-Fetch-Site": "same-origin"}) == 200
        assert post(SAME) == 409  # a second time
        wait_for(c, tid, "done")
        detail = c.get(f"/api/v1/investigations/{tid}", headers=VIEW).json()
    assert [(d["decided_by"], d["approve"]) for d in detail["decisions"]] == [
        (f"console:{OPERATOR}", True)
    ]


# Questions from the console: same rules as acting; the Answer shows on its page.

ANSWER_1 = {
    "answer": "checkout is crash looping.",
    "evidence": [{"source": "kubernetes_list_pods", "finding": "checkout restarts 5"}],
}
ANSWER_2 = {**ANSWER_1, "answer": "Still crash looping, 6 restarts now."}


def test_a_question_asked_in_the_console_answers_and_follows_up(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    from tests.test_slack import ACME, FakeSlack

    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    settings.slack_bot_token = SecretStr("xoxb-test")
    slack = FakeSlack()
    steps = [call("Answer", "a1", **ANSWER_1), call("Answer", "a2", **ANSWER_2)]
    with client(
        settings, fake_cluster, *steps, actions=True, slack=slack.transport(), acme_channel=ACME
    ) as c:

        def post(url: str, body: dict[str, str], headers: dict[str, str] = SAME) -> Any:
            return c.post(url, json=body, headers=headers)

        acme = "/api/v1/contracts/acme/questions"
        ask = {"question": "  is checkout healthy?  "}
        assert post("/api/v1/contracts/nope/questions", ask).status_code == 404
        assert post(acme, {"question": " "}).status_code == 422
        assert post(acme, {"question": "x" * 4001}).status_code == 422
        cross = {**VIEW, "Sec-Fetch-Site": "cross-site"}
        assert post(acme, ask, cross).status_code == 403
        no_token = {**AS_OPERATOR, "Origin": "http://testserver"}
        assert post(acme, ask, no_token).status_code == 401
        assert c.get("/investigations", headers=AUTH).json() == []

        asked = post(acme, ask)
        assert asked.status_code == 200
        qid = asked.json()["id"]
        q = wait_for(c, qid, "done")
        assert (q["kind"], q["contract_id"], q["title"]) == (
            "question",
            "acme",
            "is checkout healthy?",
        )
        page = c.get(f"/api/v1/investigations/{qid}", headers=VIEW).json()
        assert page["answer"]["answer"] == ANSWER_1["answer"] and page["can_follow_up"] is True

        more = f"/api/v1/investigations/{qid}/questions"
        assert post(more, {"question": "and now?"}).status_code == 200
        wait_for(c, qid, "done")
        shown = c.get(f"/api/v1/investigations/{qid}", headers=VIEW).json()
        assert shown["answer"]["answer"] == ANSWER_2["answer"]
        assert [t["question"] for t in shown["exchange"]] == ["is checkout healthy?", "and now?"][
            :1
        ]
        assert post(more, {"question": "x"}, cross).status_code == 403
        assert post("/api/v1/investigations/nope/questions", {"question": "x"}).status_code == 404
    assert slack.calls == []  # a console Question has no Slack thread


def test_a_follow_up_loads_its_checkpoint_without_warnings(
    settings: Settings, fake_cluster: Any, database_url: str, caplog: Any
) -> None:
    """The follow-up's Run loads the earlier Answer from the Postgres checkpoint."""
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    steps = [call("Answer", "a1", **ANSWER_1), call("Answer", "a2", **ANSWER_2)]
    with client(settings, fake_cluster, *steps) as c:
        asked = c.post(
            "/api/v1/contracts/acme/questions", json={"question": "healthy?"}, headers=SAME
        )
        qid = asked.json()["id"]
        wait_for(c, qid, "done")
        c.post(f"/api/v1/investigations/{qid}/questions", json={"question": "now?"}, headers=SAME)
        assert wait_for(c, qid, "done")["answer"]["answer"] == ANSWER_2["answer"]
        serde = c.app.state.checkpointer.serde  # type: ignore[attr-defined]
    assert serde is agent.CHECKPOINT_SERDE  # LangGraph warns only once per process
    assert "unregistered type" not in caplog.text and "Blocked deserialization" not in caplog.text


def test_only_a_finished_question_takes_a_follow_up(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    with client(settings, fake_cluster, call("TriageReport", "r1", **REPORT)) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        r = c.post(
            f"/api/v1/investigations/{tid}/questions", json={"question": "why?"}, headers=SAME
        )
    assert r.status_code == 409  # a Triage isn't a Question


def test_the_app_api_pages_carry_the_console_headers(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    with client(settings, fake_cluster, call("TriageReport", "c1", **REPORT)) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        pages = [
            c.get(path, headers=VIEW)
            for path in (
                f"/api/v1/investigations/{tid}",
                "/api/v1/contracts/acme/investigations",
                "/api/v1/contracts/acme/teachings",
                "/api/v1/contracts/acme/health",
            )
        ]
    for r in pages:
        assert r.status_code == 200, r.url
        assert r.headers["content-security-policy"] == CSP
        assert r.headers["x-frame-options"] == "DENY"
