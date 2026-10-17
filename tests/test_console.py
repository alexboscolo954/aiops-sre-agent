"""The web console: only an Operator's Tailscale identity gets in, and everything
it renders is escaped."""

from typing import Any

from pydantic import SecretStr

from aiops_agent.config import Settings
from aiops_agent.console import COOKIE, TEMPLATES, action_key
from aiops_agent.models import Investigation, TriageReport
from tests.conftest import REPORT, call, make_contract, make_fake_cluster
from tests.test_api import ALERT, AUTH, BANK_HOOK, BANK_URL, HOOK, URL, client
from tests.test_restart import wait_for

OPERATOR = "alex@example.com"
AS_OPERATOR = {"Tailscale-User-Login": OPERATOR, "Tailscale-User-Name": "Alex"}
ACT = {"Cookie": f"{COOKIE}={action_key('approver-token')}"}
VIEW = {**AS_OPERATOR, **ACT}  # the identity, and this browser has the token
SAME = {**VIEW, "Origin": "http://testserver"}


def test_only_a_listed_tailscale_login_gets_in(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    with client(settings, fake_cluster) as c:
        refused = [
            c.get("/console", headers=ACT),
            c.get("/console", headers={"Tailscale-User-Login": "", **ACT}),
            c.get("/console", headers={"Tailscale-User-Login": "mallory@example.com", **ACT}),
            c.get("/console", headers={**AUTH, **ACT}),  # the approver token is not a login
        ]
        # The identity alone opens only the token page: a forged header sees nothing.
        no_token = c.get("/console", headers=AS_OPERATOR, follow_redirects=False)
        bad_token = c.get(
            "/console", headers={**AS_OPERATOR, "Cookie": f"{COOKIE}=x"}, follow_redirects=False
        )
        token_page = c.get("/console/token", headers=AS_OPERATOR)
        ok = c.get("/console", headers=VIEW)
        api = c.get("/investigations", headers={"Tailscale-User-Login": OPERATOR})
    assert [r.status_code for r in refused] == [403] * 4
    for r in (no_token, bad_token):
        assert (r.status_code, r.headers["location"]) == (303, "/console/token")
    assert token_page.status_code == 200 and "Approver token" in token_page.text
    assert ok.status_code == 200 and "signed in as Alex" in ok.text and "acme" in ok.text
    assert ok.headers["content-security-policy"] == "default-src 'self'; frame-ancestors 'none'"
    assert ok.headers["x-frame-options"] == "DENY"
    assert api.status_code in {401, 403}  # the API still wants the approver token


def test_the_console_is_off_without_operators(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    settings.database_url = SecretStr(database_url)
    with client(settings, fake_cluster) as c:
        assert c.get("/console", headers=VIEW).status_code == 404


def test_everything_rendered_is_escaped() -> None:
    hostile = make_contract(contract_id="evil").model_copy(
        update={"name": "<script>alert(1)</script>"}
    )
    html = TEMPLATES.get_template("index.html").render(
        name="<img src=x onerror=alert(1)>", login="x", contracts=[hostile]
    )
    assert "<script>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img" not in html and "&lt;img src=x onerror=alert(1)&gt;" in html


# Investigations: list, filter by Contract, detail; acting needs the token and same origin.


EVICT = call(
    "kubernetes_evict_pod", "c1", cluster="test", namespace="shop", name="checkout-7d9f-abc"
)


def test_investigations_are_listed_filtered_and_shown(
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
        everything = c.get("/console", headers=VIEW).text
        only_bank = c.get("/console?contract=bank", headers=VIEW).text
        unknown = c.get("/console?contract=nope", headers=VIEW).text
        detail = c.get(f"/console/investigations/{a}", headers=VIEW)
        missing = c.get("/console/investigations/nope", headers=VIEW)
        anonymous = c.get(f"/console/investigations/{a}", headers=ACT)
    assert a in everything and b in everything and a in unknown  # unknown = all
    assert b in only_bank and a not in only_bank
    assert detail.status_code == 200 and detail.headers["x-frame-options"] == "DENY"
    assert REPORT["summary"] in detail.text and "bank&#39;s own summary" not in detail.text
    assert "kubernetes_list_pods" in detail.text and "cluster" in detail.text  # the tool call
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
        assert 'name="deadline"' in c.get(f"/console/investigations/{tid}", headers=VIEW).text
        url = f"/console/investigations/{tid}/decision"
        body = {"approve": "1", "deadline": repr(t["deadline"])}

        def post(headers: dict[str, str]) -> int:
            return c.post(url, data=body, headers=headers, follow_redirects=False).status_code

        origin = {"Origin": "http://testserver"}
        assert post({**AS_OPERATOR, **origin}) == 303  # no token: off to the token page
        not_key = {"Cookie": f"{COOKIE}=approver-token"}  # the token itself isn't the key
        assert post({**AS_OPERATOR, **origin, **not_key}) == 303
        assert post({**VIEW, "Sec-Fetch-Site": "cross-site"}) == 403
        assert post({**VIEW, "Origin": "https://evil.example"}) == 403
        assert post(VIEW) == 403  # neither Sec-Fetch-Site nor Origin
        assert post({**ACT, **origin}) == 403  # no identity
        body["deadline"] = "1.0"  # another pause
        assert post(SAME) == 409
        body["deadline"] = repr(t["deadline"])
        assert post({**VIEW, "Sec-Fetch-Site": "same-origin"}) == 303
        assert post(SAME) == 409  # a second time
        wait_for(c, tid, "done")
        detail = c.get(f"/console/investigations/{tid}", headers=VIEW).text
    assert f"console:{OPERATOR}" in detail and "approved" in detail


def test_the_token_form_sets_a_cookie_that_proves_the_token(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    with client(settings, fake_cluster) as c:
        wrong = c.post(
            "/console/token",
            data={"token": "nope"},
            headers={**AS_OPERATOR, "Origin": "http://testserver"},
        )
        cross = c.post(
            "/console/token",
            data={"token": "approver-token"},
            headers={**AS_OPERATOR, "Sec-Fetch-Site": "cross-site"},
        )
        ok = c.post(
            "/console/token",
            data={"token": "approver-token"},
            headers={**AS_OPERATOR, "Origin": "http://testserver"},
            follow_redirects=False,
        )
    assert wrong.status_code == 403 and cross.status_code == 403
    assert ok.status_code == 303
    cookie = ok.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}={action_key('approver-token')};")
    assert "approver-token" not in cookie
    for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/console"):
        assert flag in cookie, flag


def test_an_investigation_page_escapes_everything() -> None:
    hostile = "<script>alert(1)</script>"
    t = Investigation(
        id="i",
        contract_id="acme",
        title=hostile,
        started=0,
        status="awaiting_approval",
        deadline=1.0,
        error=hostile,
        pending=[{"name": "x", "description": hostile}],
        report=TriageReport(**{**REPORT, "summary": hostile}),
    )
    html = TEMPLATES.get_template("investigation.html").render(
        name="n",
        login="l",
        t=t,
        can_act=True,
        decisions=[],
        tool_calls=[{"tool": hostile, "args": {"a": hostile}, "result": hostile, "is_error": True}],
    )
    assert "<script>" not in html and html.count("&lt;script&gt;") >= 5


# Questions from the console: same rules as acting; the Answer opens on its page.

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

        def post(url: str, data: dict[str, str], headers: dict[str, str] = SAME) -> Any:
            return c.post(url, data=data, headers=headers, follow_redirects=False)

        ask = {"contract": "acme", "question": "  is checkout healthy?  "}
        assert post("/console/questions", {**ask, "contract": "nope"}).status_code == 400
        assert post("/console/questions", {**ask, "question": " "}).status_code == 400
        assert post("/console/questions", {**ask, "question": "x" * 4001}).status_code == 400
        cross = {**VIEW, "Sec-Fetch-Site": "cross-site"}
        assert post("/console/questions", ask, cross).status_code == 403
        no_token = {**AS_OPERATOR, "Origin": "http://testserver"}
        assert post("/console/questions", ask, no_token).status_code == 303  # to the token page
        assert c.get("/investigations", headers=AUTH).json() == []

        asked = post("/console/questions", ask)
        assert asked.status_code == 303
        qid = asked.headers["location"].rsplit("/", 1)[1]
        q = wait_for(c, qid, "done")
        assert (q["kind"], q["contract_id"], q["title"]) == (
            "question",
            "acme",
            "is checkout healthy?",
        )
        page = c.get(asked.headers["location"], headers=VIEW).text
        assert ANSWER_1["answer"] in page and "Follow up" in page and "refresh" not in page

        more = f"/console/investigations/{qid}/questions"
        assert post(more, {"question": "and now?"}).status_code == 303
        wait_for(c, qid, "done")
        assert ANSWER_2["answer"] in c.get(asked.headers["location"], headers=VIEW).text
        assert post(more, {"question": "x"}, cross).status_code == 403
        assert post("/console/investigations/nope/questions", {"question": "x"}).status_code == 404
    assert slack.calls == []  # a console Question has no Slack thread


def test_only_a_finished_question_takes_a_follow_up(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    with client(settings, fake_cluster, call("TriageReport", "r1", **REPORT)) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        r = c.post(
            f"/console/investigations/{tid}/questions",
            data={"question": "why?"},
            headers=SAME,
            follow_redirects=False,
        )
    assert r.status_code == 409  # a Triage isn't a Question


def test_a_running_investigation_page_reloads_itself() -> None:
    t = Investigation(id="i", kind="question", contract_id="acme", title="q", started=0)
    html = TEMPLATES.get_template("investigation.html").render(
        name="n", login="l", t=t, decisions=[], tool_calls=[]
    )
    assert '<meta http-equiv="refresh" content="5">' in html and "Follow up" not in html
