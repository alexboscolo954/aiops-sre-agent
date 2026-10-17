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


def test_only_a_listed_tailscale_login_gets_in(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    with client(settings, fake_cluster) as c:
        refused = [
            c.get("/console"),
            c.get("/console", headers={"Tailscale-User-Login": ""}),
            c.get("/console", headers={"Tailscale-User-Login": "mallory@example.com"}),
            c.get("/console", headers=AUTH),  # the approver token is not a login
        ]
        ok = c.get("/console", headers=AS_OPERATOR)
        api = c.get("/investigations", headers={"Tailscale-User-Login": OPERATOR})
    assert [r.status_code for r in refused] == [403] * 4
    assert ok.status_code == 200 and "signed in as Alex" in ok.text and "acme" in ok.text
    assert ok.headers["content-security-policy"] == "default-src 'self'; frame-ancestors 'none'"
    assert ok.headers["x-frame-options"] == "DENY"
    assert api.status_code in {401, 403}  # the API still wants the approver token


def test_the_console_is_off_without_operators(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    settings.database_url = SecretStr(database_url)
    with client(settings, fake_cluster) as c:
        assert c.get("/console", headers=AS_OPERATOR).status_code == 404


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


SAME = {**AS_OPERATOR, "Origin": "http://testserver"}
ACT = {"Cookie": f"{COOKIE}={action_key('approver-token')}"}
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
        everything = c.get("/console", headers=AS_OPERATOR).text
        only_bank = c.get("/console?contract=bank", headers=AS_OPERATOR).text
        unknown = c.get("/console?contract=nope", headers=AS_OPERATOR).text
        detail = c.get(f"/console/investigations/{a}", headers=AS_OPERATOR)
        missing = c.get("/console/investigations/nope", headers=AS_OPERATOR)
        anonymous = c.get(f"/console/investigations/{a}")
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
        page = c.get(f"/console/investigations/{tid}", headers=AS_OPERATOR).text
        assert "enter the approver token" in page and 'name="deadline"' not in page
        assert (
            'name="deadline"'
            in c.get(f"/console/investigations/{tid}", headers={**AS_OPERATOR, **ACT}).text
        )
        url = f"/console/investigations/{tid}/decision"
        body = {"approve": "1", "deadline": repr(t["deadline"])}

        def post(headers: dict[str, str], cookie: dict[str, str] = ACT) -> int:
            r = c.post(url, data=body, headers={**headers, **cookie}, follow_redirects=False)
            return r.status_code

        assert post(SAME, cookie={}) == 403  # no token
        assert post(SAME, cookie={"Cookie": f"{COOKIE}=approver-token"}) == 403  # not the key
        assert post({**AS_OPERATOR, "Sec-Fetch-Site": "cross-site"}) == 403
        assert post({**AS_OPERATOR, "Origin": "https://evil.example"}) == 403
        assert post(AS_OPERATOR) == 403  # neither Sec-Fetch-Site nor Origin
        assert post({"Origin": "http://testserver"}) == 403  # no identity
        body["deadline"] = "1.0"  # another pause
        assert post(SAME) == 409
        body["deadline"] = repr(t["deadline"])
        assert post({**AS_OPERATOR, "Sec-Fetch-Site": "same-origin"}) == 303
        assert post(SAME) == 409  # a second time
        wait_for(c, tid, "done")
        detail = c.get(f"/console/investigations/{tid}", headers=AS_OPERATOR).text
    assert f"console:{OPERATOR}" in detail and "approved" in detail


def test_the_token_form_sets_a_cookie_that_proves_the_token(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    with client(settings, fake_cluster) as c:
        wrong = c.post("/console/token", data={"token": "nope"}, headers=SAME)
        cross = c.post(
            "/console/token",
            data={"token": "approver-token"},
            headers={**AS_OPERATOR, "Sec-Fetch-Site": "cross-site"},
        )
        ok = c.post(
            "/console/token",
            data={"token": "approver-token"},
            headers=SAME,
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
