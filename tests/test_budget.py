"""Budgets: at 100% a new Run is refused with no model call, but the Operator is
still told; a resume always runs; 80% and 100% notices post once a month."""

from typing import Any

import psycopg
import pytest
from pydantic import SecretStr

from aiops_agent.config import Settings
from tests.conftest import REPORT, call, make_contract, make_fake_cluster
from tests.test_api import ALERT, AUTH, BANK_HOOK, BANK_URL, HOOK, URL, client
from tests.test_console import OPERATOR, SAME
from tests.test_cost import EVICT, HAIKU, used
from tests.test_restart import wait_for
from tests.test_slack import ACME, FakeSlack

TEN_K = 0.001  # HAIKU.cost(10_000, 0)
REFUSED = "has used its monthly budget"


@pytest.fixture
def priced(settings: Settings, database_url: str) -> Settings:
    settings.database_url = SecretStr(database_url)
    settings.model_prices = {settings.model: HAIKU}
    settings.slack_bot_token = SecretStr("xoxb-test")
    return settings


def report(call_id: str) -> Any:
    return used(call("TriageReport", call_id, **REPORT), 10_000, 0)


def alert(key: str) -> dict[str, Any]:
    return {**ALERT, "groupKey": key, "alerts": [{**ALERT["alerts"][0], "fingerprint": key}]}


def notices(slack: FakeSlack) -> list[str]:
    return [
        p["text"]
        for m, p, _ in slack.calls
        if m == "chat.postMessage" and "thread_ts" not in p and "blocks" not in p
    ]


def model_calls(database_url: str) -> int:
    with psycopg.connect(database_url) as conn:
        return int(conn.execute("select count(*) from usage").fetchone()[0])  # type: ignore[index]


def test_at_100_percent_an_alert_is_refused_and_still_told(
    priced: Settings, fake_cluster: Any, database_url: str
) -> None:
    assert HAIKU.cost(10_000, 0) == pytest.approx(TEN_K)
    slack = FakeSlack()
    budget = {"monthly_budget_usd": 1.1 * TEN_K}
    steps = [report("r1"), report("r2")]
    with client(
        priced, fake_cluster, *steps, slack=slack.transport(), acme_channel=ACME, acme=budget
    ) as c:
        first = c.post(URL, json=alert("a1"), headers=HOOK).json()["investigation"]
        wait_for(c, first, "done")  # 91%: the 80% notice, right after the Run
        slack.until(4)
        assert len(notices(slack)) == 1 and "80%" in notices(slack)[0]
        second = c.post(URL, json=alert("a2"), headers=HOOK).json()["investigation"]
        wait_for(c, second, "done")  # started under budget, ends over: the 100% notice
        refused = c.post(URL, json=alert("a3"), headers=HOOK).json()
        t = wait_for(c, refused["investigation"], "failed")
        again = c.post(URL, json=alert("a3"), headers=HOOK).json()
        slack.until(9)  # 3 per Triage (parent, update, reply) and the notices
    assert refused["status"] == "refused" and REFUSED in refused["reason"]
    assert REFUSED in t["error"] and "$0.0020 of $0.0011" in t["error"]
    assert again["status"] == "duplicate"  # remembered: no second refusal
    assert model_calls(database_url) == 2  # the refusal never called the model
    said = notices(slack)
    assert len(said) == 2, said  # each once, though checked after every Run and refusal
    assert said[0].startswith(":warning: *[acme]* has used 80% of its monthly budget")
    assert said[1].startswith(":no_entry: *[acme]* has used its monthly budget")
    told = [p["text"] for _, p, _ in slack.calls if "thread_ts" in p]
    assert any(text.startswith("Investigation failed: Contract 'acme' has used") for text in told)


def test_a_resume_always_runs_even_over_budget(
    priced: Settings, fake_cluster: Any, database_url: str
) -> None:
    steps = [used(EVICT, 10_000, 0), report("r2")]
    budget = {"monthly_budget_usd": 0.5 * TEN_K}
    with client(priced, fake_cluster, *steps, actions=True, acme=budget) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "awaiting_approval")  # this Run alone went over
        c.post(f"/investigations/{tid}/decision", json={"approve": True}, headers=AUTH)
        t = wait_for(c, tid, "done")
    assert t["report"] is not None and t["executed_actions"]
    assert model_calls(database_url) == 2


def test_questions_and_follow_ups_are_refused_over_budget(
    priced: Settings, fake_cluster: Any
) -> None:
    priced.console_operators = {OPERATOR}
    answer = {"answer": "fine", "evidence": [{"source": "kubernetes_list_pods", "finding": "x"}]}
    steps = [used(call("Answer", f"a{i}", **answer), 10_000, 0) for i in (1, 2)]
    budget = {"monthly_budget_usd": 1.1 * TEN_K}
    with client(priced, fake_cluster, *steps, acme=budget) as c:

        def ask(url: str, data: dict[str, str]) -> str:
            r = c.post(url, data=data, headers=SAME, follow_redirects=False)
            return str(r.headers["location"]).rsplit("/", 1)[1]

        qid = ask("/console/questions", {"contract": "acme", "question": "healthy?"})
        wait_for(c, qid, "done")
        ask(f"/console/investigations/{qid}/questions", {"question": "and now?"})
        wait_for(c, qid, "done")  # under budget when it started
        ask(f"/console/investigations/{qid}/questions", {"question": "and now?"})
        follow_up = wait_for(c, qid, "failed")
        new = ask("/console/questions", {"contract": "acme", "question": "again?"})
        refused = wait_for(c, new, "failed")
    assert REFUSED in follow_up["error"] and REFUSED in refused["error"]


def test_one_contract_over_budget_never_blocks_another(
    priced: Settings, fake_cluster: Any, database_url: str
) -> None:
    bank = make_contract(contract_id="bank", webhook_token="bank-token", monthly_budget_usd=1.0)
    more = {"bank": (bank, make_fake_cluster())}
    steps = [report("r1"), report("r2")]
    budget = {"monthly_budget_usd": 0.5 * TEN_K}
    with client(priced, fake_cluster, *steps, more=more, acme=budget) as c:
        a = c.post(URL, json=alert("a1"), headers=HOOK).json()["investigation"]
        wait_for(c, a, "done")
        assert c.post(URL, json=alert("a2"), headers=HOOK).json()["status"] == "refused"
        b = c.post(BANK_URL, json=ALERT, headers=BANK_HOOK).json()
        assert b["status"] == "accepted"
        wait_for(c, b["investigation"], "done")
    with psycopg.connect(database_url) as conn:
        spend = dict(conn.execute("select contract_id, sum(cost_usd) from usage group by 1"))
    assert spend == {"acme": pytest.approx(TEN_K), "bank": pytest.approx(TEN_K)}
