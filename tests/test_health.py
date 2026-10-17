"""Health: each Contract's integrations checked through its own tools, its last
successful Investigation, and its config, with secret values never shown."""

from typing import Any

from fastapi.testclient import TestClient
from kubernetes.client import ApiException
from pydantic import SecretStr

from aiops_agent import agent, contracts
from aiops_agent.api import create_app
from aiops_agent.config import Settings
from tests.conftest import REPORT, call, make_contract, make_fake_cluster, scripted
from tests.test_api import ALERT, HOOK, URL, client
from tests.test_console import AS_OPERATOR, OPERATOR, VIEW
from tests.test_restart import wait_for


def section(html: str, contract_id: str) -> str:
    """One Contract's part of the health page."""
    start = html.index(f"<h2><code>{contract_id}</code>")
    end = html.find("<h2>", start + 1)
    return html[start:end]


def test_each_contract_shows_its_own_checks_and_last_success(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    broken = make_fake_cluster()
    broken[1].list_namespaced_deployment.side_effect = ApiException(
        403, "Forbidden token=abcdefghijklmnop1234"
    )
    bank = make_contract(contract_id="bank", webhook_token="bank-token")
    with client(
        settings, fake_cluster, call("TriageReport", "r1", **REPORT), more={"bank": (bank, broken)}
    ) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        later = {**ALERT, "groupKey": "later"}  # no model steps left: it fails
        wait_for(c, c.post(URL, json=later, headers=HOOK).json()["investigation"], "failed")
        page = c.get("/console/health", headers=VIEW)
        no_token = c.get("/console/health", headers=AS_OPERATOR, follow_redirects=False)
    assert page.status_code == 200 and no_token.status_code == 303
    acme, other = section(page.text, "acme"), section(page.text, "bank")
    assert "<td>kubernetes test</td><td>ok</td>" in acme and "FAILING" not in acme
    assert f'href="/console/investigations/{tid}"' in acme
    assert "<td>kubernetes test</td><td>FAILING</td>" in other
    assert "Kubernetes API 403" in other and "none yet" in other
    assert "abcdefghijklmnop1234" not in page.text  # a check's error is redacted
    assert "approver-token" not in page.text and "**********" in page.text  # Hub settings


def test_secret_values_never_show_and_unbuildable_tools_fail_the_check(
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
        page = c.get("/console/health", headers=VIEW).text
    assert secret not in page
    assert "<code>prometheus-token</code> loaded" in section(page, "demo-shop")
    bank = section(page, "demo-bank")
    assert "<td>tools</td><td>FAILING</td>" in bank and "RuntimeError: kubeconfig not found" in bank
    assert "abcdefghijklmnop1234" not in bank  # errors are redacted too
