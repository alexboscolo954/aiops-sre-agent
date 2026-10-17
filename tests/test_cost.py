"""Cost: every model call's tokens, priced per call, summed per Investigation and per
Contract per month. Budgets refuse new work at 100% (test_budget)."""

from typing import Any

import pytest
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from aiops_agent import agent
from aiops_agent.api import create_app
from aiops_agent.config import LongContext, Price, Settings
from aiops_agent.store import Store, connect, month_start
from tests.conftest import REPORT, call, make_contract, scripted
from tests.test_api import ALERT, AUTH, HOOK, URL, client
from tests.test_restart import wait_for

HAIKU = Price(input=0.10, output=0.50, long=LongContext(over=100_000, input=0.50, output=2.50))
EVICT = call(
    "kubernetes_evict_pod", "c1", cluster="test", namespace="shop", name="checkout-7d9f-abc"
)


def used(message: AIMessage, input_tokens: int, output_tokens: int) -> AIMessage:
    message.usage_metadata = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
    return message


def test_a_call_is_priced_whole_at_its_prompt_size() -> None:
    assert HAIKU.cost(50_000, 1_000_000) == pytest.approx(0.505)
    assert HAIKU.cost(100_000, 1_000) == pytest.approx(0.0105)  # at the line: base
    assert HAIKU.cost(100_001, 1_000) == pytest.approx(0.0525005)  # over: all of it 5x
    assert Price(input=2, output=10).cost(200_000, 0) == pytest.approx(0.40)  # no tier


@pytest.fixture
def priced(settings: Settings, database_url: str) -> Settings:
    settings.database_url = SecretStr(database_url)
    settings.model_prices = {settings.model: HAIKU}
    return settings


def usage_rows(database_url: str) -> list[tuple[str, int, int, float | None]]:
    import psycopg

    with psycopg.connect(database_url) as conn:
        rows = conn.execute(
            "select model, input_tokens, output_tokens, cost_usd from usage order by id"
        )
        return [(r[0], r[1], r[2], r[3]) for r in rows.fetchall()]


def test_each_model_call_is_recorded_and_a_resume_counts_only_its_own(
    priced: Settings, fake_cluster: Any, database_url: str
) -> None:
    from tests.test_console import OPERATOR, VIEW

    priced.console_operators = {OPERATOR}
    steps = [used(EVICT, 1000, 50), used(call("TriageReport", "c2", **REPORT), 3000, 200)]
    budget = {"monthly_budget_usd": 0.002}
    with client(priced, fake_cluster, *steps, actions=True, acme=budget) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "awaiting_approval")
        c.post(f"/investigations/{tid}/decision", json={"approve": True}, headers=AUTH)
        wait_for(c, tid, "done")
        page = c.get(f"/console/investigations/{tid}", headers=VIEW).text
        index = c.get("/console", headers=VIEW).text
    assert "Tokens: 4000 in, 250 out" in page and "cost: $0.0005" in page
    assert "$0.0005 of $0.00 (26%)" in index  # $0.000525 of a $0.002 budget
    rows = usage_rows(database_url)
    assert [r[:3] for r in rows] == [(priced.model, 1000, 50), (priced.model, 3000, 200)]
    assert [r[3] for r in rows] == pytest.approx([HAIKU.cost(1000, 50), HAIKU.cost(3000, 200)])


@pytest.mark.anyio
async def test_spend_is_one_contracts_and_one_months(database_url: str) -> None:
    from aiops_agent.models import Investigation

    async with connect(database_url) as pool:
        st = Store(pool)
        await st.migrate()
        for cid in ("acme", "bank"):
            await st.insert(Investigation(id=cid, contract_id=cid, title="t", started=0))
        await st.record_usage("acme", "acme", "m", 10, 1, 1.25)
        await st.record_usage("acme", "acme", "m", 10, 1, None)  # unpriced: tokens only
        await st.record_usage("bank", "bank", "m", 10, 1, 7.0)
        last_month = month_start(month_start(agent_now()) - 1)
        await st._exec(
            "insert into usage (investigation_id, contract_id, model, input_tokens, "
            "output_tokens, cost_usd, at) values ('acme', 'acme', 'm', 1, 1, 100, %s)",
            (last_month,),
        )
        assert await st.month_spend("acme", agent_now()) == pytest.approx(1.25)
        assert await st.month_spend("bank", agent_now()) == pytest.approx(7.0)
        totals = await st.investigation_usage("acme")
        assert (totals["input_tokens"], totals["cost_usd"]) == (21, pytest.approx(101.25))


def agent_now() -> float:
    from aiops_agent.store import now

    return now()


def test_a_failed_usage_write_never_fails_the_run(
    priced: Settings, fake_cluster: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*args: Any) -> None:
        raise ConnectionError("database down")

    monkeypatch.setattr(Store, "record_usage", broken)
    steps = [used(call("TriageReport", "c1", **REPORT), 100, 10)]
    with client(priced, fake_cluster, *steps) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")


def test_budgets_need_a_price_and_contract_models_the_hubs_gateway(
    settings: Settings, database_url: str
) -> None:
    settings.approver_token = SecretStr("approver-token")
    settings.database_url = SecretStr(database_url)
    budgeted = make_contract(monthly_budget_usd=20)
    with pytest.raises(RuntimeError, match="has a budget, but its model"):
        create_app(settings, scripted(), by_id={"acme": budgeted})
    settings.model_prices = {"openai:cheap": HAIKU}
    cheap = make_contract(model="openai:cheap", monthly_budget_usd=20)
    create_app(settings, scripted(), by_id={"acme": cheap})  # priced: fine
    settings.model, settings.model_base_url = "openai:hub", "https://openrouter.ai/api/v1"
    elsewhere = make_contract(model="anthropic:claude-haiku-5-5")
    with pytest.raises(RuntimeError, match="through the Hub's gateway"):
        create_app(settings, scripted(), by_id={"acme": elsewhere})
    create_app(settings, scripted(), by_id={"acme": cheap})


def test_each_contract_runs_on_its_own_model(
    priced: Settings, fake_cluster: Any, monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    from aiops_agent import api

    built: list[str] = []

    def build(s: Settings) -> Any:
        built.append(s.model)
        return scripted(used(call("TriageReport", "c1", **REPORT), 100, 10))

    monkeypatch.setattr(agent, "build_model", build)
    priced.model_prices["openai:cheap"] = HAIKU
    priced.approver_token = SecretStr("approver-token")
    acme = make_contract(webhook_token="hook-token", model="openai:cheap")

    def mcp(c: Any) -> agent.Toolbox:
        return agent.build_mcp(c, priced, {cl.name: fake_cluster for cl in c.clusters})

    from fastapi.testclient import TestClient

    with TestClient(api.create_app(priced, None, mcp, {"acme": acme})) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
    assert built == ["openai:cheap"]
    assert [r[0] for r in usage_rows(database_url)] == ["openai:cheap"]
