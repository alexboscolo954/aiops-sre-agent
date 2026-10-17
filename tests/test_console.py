"""The web console: only an Operator's Tailscale identity gets in, and everything
it renders is escaped."""

from typing import Any

from pydantic import SecretStr

from aiops_agent.config import Settings
from aiops_agent.console import TEMPLATES
from tests.conftest import make_contract
from tests.test_api import AUTH, client

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
