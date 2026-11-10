"""Health: each Contract's integrations checked through its own tools, its last
successful Investigation, and its config, with secret values never shown."""

from typing import Any

from fastapi.testclient import TestClient
from kubernetes.client import ApiException
from pydantic import SecretStr

from squero import agent, contracts
from squero.api import create_app
from squero.config import Settings
from tests.conftest import REPORT, call, make_contract, make_fake_cluster, scripted
from tests.test_api import ALERT, HOOK, URL, client
from tests.test_console import AS_OPERATOR, OPERATOR, VIEW
from tests.test_restart import wait_for


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
        acme_r = c.get("/api/v1/contracts/acme/health", headers=VIEW)
        bank_r = c.get("/api/v1/contracts/bank/health", headers=VIEW)
        no_token = c.get("/api/v1/contracts/acme/health", headers=AS_OPERATOR)
    assert acme_r.status_code == 200 and no_token.status_code == 401
    acme, other = acme_r.json(), bank_r.json()
    (acme_probe,) = acme["integrations"]
    (bank_probe,) = other["integrations"]
    assert acme_probe == {**acme_probe, "name": "kubernetes test", "ok": True}
    assert acme["last"]["id"] == tid  # its last finished Investigation
    assert bank_probe["name"] == "kubernetes test" and bank_probe["ok"] is False
    assert "Kubernetes API 403" in bank_probe["detail"] and other["last"] is None
    assert "abcdefghijklmnop1234" not in acme_r.text + bank_r.text  # a check's error is redacted
    assert "approver-token" not in acme_r.text and "**********" in acme["hub"]  # Hub settings


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
        shop_r = c.get("/api/v1/contracts/demo-shop/health", headers=VIEW)
        bank_r = c.get("/api/v1/contracts/demo-bank/health", headers=VIEW)
    assert secret not in shop_r.text
    assert shop_r.json()["secrets"]["prometheus-token"] is True  # named, and it decrypted
    tools = [p for p in bank_r.json()["integrations"] if p["name"] == "tools"]
    assert tools[0]["ok"] is False and "RuntimeError: kubeconfig not found" in tools[0]["detail"]
    assert "abcdefghijklmnop1234" not in bank_r.text  # errors are redacted too


def test_hub_settings_never_show_credentials_in_plain_strings() -> None:
    from squero.api import shown_settings

    settings = Settings(
        _env_file=None,
        model_headers={"Authorization": "Bearer sk-live-abcdefghijklmnop", "x-team": "sre"},
        model_base_url="https://user:hunter2@gateway.example/v1",
        model_api_key=SecretStr("sk-key-abcdefghijklmnop"),
    )
    shown = str(shown_settings(settings))
    for value in ("sk-live-abcdefghijklmnop", "hunter2", "user:", "sre", "sk-key-abc"):
        assert value not in shown, value
    assert "gateway.example" in shown and "Authorization" in shown
