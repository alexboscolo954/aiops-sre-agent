"""Save as Scenario: a finished Investigation becomes a draft Scenario that replays to
the same tool calls and the same results, with the tools production offered."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from langchain.messages import ToolMessage
from pydantic import SecretStr

from aiops_agent import agent, evals
from aiops_agent.config import Settings
from aiops_agent.models import AlertGroup, Investigation
from tests.conftest import REPORT, call, make_contract, make_fake_cluster, scripted
from tests.test_api import ALERT, BANK_HOOK, BANK_URL, HOOK, URL, client
from tests.test_console import AS_OPERATOR, OPERATOR, SAME, VIEW
from tests.test_restart import wait_for

SECRET = "token=abcdefghijklmnop1234"
LIST = ("kubernetes_list_pods", {"cluster": "test", "namespace": "shop"})
PROM = ("prometheus_query", {"promql": "up"})
SEARCH = ("runbooks_search_runbooks", {"keywords": "oom"})
ANSWER = {
    "answer": "checkout is crash looping.",
    "evidence": [{"source": "kubernetes_list_pods", "finding": "restarts"}],
}


@pytest.fixture
def full(settings: Settings, database_url: str, tmp_path: Path) -> dict[str, Any]:
    """acme with kubernetes, Prometheus (unreachable: its call errors) and Runbooks."""
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    (tmp_path / "oom.md").write_text("---\ntitle: OOM\nalerts: [X]\n---\nRaise the limit.\n")
    integrations = [
        {"name": "kubernetes"},
        {"name": "prometheus", "url": "http://prometheus.invalid"},
        {"name": "runbooks"},
    ]
    return {"integrations": integrations, "runbook_dirs": (tmp_path,)}


def steps(*calls: tuple[str, dict[str, Any]], last: Any) -> list[Any]:
    return [call(name, f"s{i}", **args) for i, (name, args) in enumerate(calls)] + [last]


def download(c: Any, tid: str) -> tuple[Any, dict[str, Any], str]:
    r = c.get(f"/console/investigations/{tid}/scenario.yaml", headers=VIEW)
    return r, yaml.safe_load(r.text), r.text


def replay(settings: Settings, scenario: dict[str, Any], model: Any) -> Any:
    contract = evals.scenario_contract(
        scenario.get("namespace", ""),
        scenario.get("enable_actions", False),
        [Path("no-runbooks")],
        scenario.get("clusters"),
        scenario.get("integrations"),
    )
    kind = "question" if "question" in scenario else "check" if "check" in scenario else "triage"
    toolbox = evals.replay_server(contract, settings, scenario["tools"])
    return agent.open_agent(settings, toolbox, model, kind=kind)


async def tool_texts(a: Any, thread: str) -> dict[str, tuple[str, str]]:
    state = await a.aget_state({"configurable": {"thread_id": thread}})
    return {
        m.name: (m.status, agent.text_of(m))
        for m in state.values["messages"]
        if isinstance(m, ToolMessage) and m.name
    }


@pytest.mark.anyio
async def test_a_saved_triage_replays_to_the_same_calls_and_results(
    settings: Settings, fake_cluster: Any, full: dict[str, Any]
) -> None:
    hostile = {**ALERT, "commonAnnotations": {"summary": f"see {SECRET}"}}
    script = steps(LIST, PROM, SEARCH, last=call("TriageReport", "r", **REPORT))
    with client(settings, fake_cluster, *script, acme=full) as c:
        tid = c.post(URL, json=hostile, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        r, scenario, text = download(c, tid)
        page = c.get(f"/console/investigations/{tid}", headers=VIEW).text
    assert r.status_code == 200 and "Save as Scenario" in page
    assert r.headers["content-disposition"] == f'attachment; filename="acme-{tid[:8]}.yaml"'
    assert text.startswith(f"# Draft Scenario from triage {tid} (acme)")
    assert SECRET not in text and "[REDACTED]" in text  # the alert went through redact
    assert scenario["clusters"] == {"test": ["shop"]}
    assert scenario["integrations"] == ["kubernetes", "prometheus", "runbooks"]
    assert set(scenario["tools"]) == {"kubernetes_list_pods", "prometheus_query"}  # no runbooks_
    assert scenario["expect"] == {
        "category": ["resource_limits"],
        "keywords": [],
        "max_tool_calls": 6,
    }
    assert set(scenario["tools"]["prometheus_query"][0]["result"]) == {"error"}

    # Replay it, as the eval runner would, with the same calls.
    again = steps(LIST, PROM, last=call("TriageReport", "r", **REPORT))
    async with replay(settings, scenario, scripted(*again)) as a:
        outcome, _ = await evals.triage(
            a, AlertGroup.model_validate(scenario["alert"]), "r", scenario["expect"]
        )
        seen = await tool_texts(a, "r")
    assert outcome.tool_calls[:2] == ["kubernetes_list_pods", "prometheus_query"]
    want = scenario["tools"]["kubernetes_list_pods"][0]["result"]
    assert seen["kubernetes_list_pods"][0] == "success"
    assert json.loads(seen["kubernetes_list_pods"][1]) == want  # the same result, as data
    assert seen["prometheus_query"][0] == "error"  # an error replays as an error...
    recorded_error = scenario["tools"]["prometheus_query"][0]["result"]["error"]
    assert (
        seen["prometheus_query"][1] == recorded_error
    )  # ...from the recording, not "unknown tool"
    assert evals.score(scenario, outcome) == []


@pytest.mark.anyio
async def test_a_saved_question_replays_and_scores(
    settings: Settings, fake_cluster: Any, full: dict[str, Any]
) -> None:
    script = steps(LIST, last=call("Answer", "a", **ANSWER))
    with client(settings, fake_cluster, *script, acme=full) as c:
        asked = c.post(
            "/console/questions",
            data={"contract": "acme", "question": f"is checkout ok? {SECRET}"},
            headers=SAME,
            follow_redirects=False,
        )
        qid = asked.headers["location"].rsplit("/", 1)[1]
        wait_for(c, qid, "done")
        _, scenario, text = download(c, qid)
    assert scenario["question"] == "is checkout ok? token=[REDACTED]" and SECRET not in text
    assert scenario["expect"] == {
        "keywords": [],
        "evidence": ["kubernetes_list_pods"],
        "max_tool_calls": 4,
    }
    async with replay(
        settings, scenario, scripted(*steps(LIST, last=call("Answer", "a", **ANSWER)))
    ) as a:
        outcome = await agent.ask(a, scenario["question"], "q")
    assert evals.score_answer(scenario, outcome) == []


def test_only_a_finished_investigation_with_its_input_saves(
    settings: Settings, fake_cluster: Any, full: dict[str, Any], database_url: str
) -> None:
    import asyncio

    from aiops_agent.store import Store, connect

    evict = call("kubernetes_evict_pod", "e", cluster="test", namespace="shop", name="p")
    acting = {**full, "integrations": [{"name": "kubernetes", "enable_actions": True}]}
    with client(settings, fake_cluster, evict, actions=True, acme=acting) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "awaiting_approval")
        paused = c.get(f"/console/investigations/{tid}/scenario.yaml", headers=VIEW)

        async def old() -> None:  # recorded before migration 0008: no input
            async with connect(database_url) as pool:
                t = Investigation(id="old", contract_id="acme", title="t", started=0, status="done")
                await Store(pool).insert(t)

        asyncio.run(old())
        before = c.get("/console/investigations/old/scenario.yaml", headers=VIEW)
        no_token = c.get(
            f"/console/investigations/{tid}/scenario.yaml",
            headers=AS_OPERATOR,
            follow_redirects=False,
        )
        unknown = c.get("/console/investigations/nope/scenario.yaml", headers=VIEW)
    assert paused.status_code == 409 and before.status_code == 409
    assert no_token.status_code == 303 and unknown.status_code == 404


def test_one_contracts_scenario_holds_none_of_anothers_calls(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    theirs = make_fake_cluster()
    theirs[0].list_namespaced_pod.return_value.items[0].metadata.name = "bank-only-pod-xyz"
    bank = make_contract(contract_id="bank", webhook_token="bank-token")
    script = [
        call("kubernetes_list_pods", "a1", **LIST[1]),
        call("TriageReport", "a2", **REPORT),
        call("kubernetes_list_pods", "b1", **LIST[1]),
        call("TriageReport", "b2", **REPORT),
    ]
    with client(settings, fake_cluster, *script, more={"bank": (bank, theirs)}) as c:
        a = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, a, "done")
        b = c.post(BANK_URL, json=ALERT, headers=BANK_HOOK).json()["investigation"]
        wait_for(c, b, "done")
        _, mine, text = download(c, a)
    assert "bank-only-pod-xyz" not in text and len(mine["tools"]["kubernetes_list_pods"]) == 1


def test_an_approved_action_becomes_an_allowed_one(
    settings: Settings, fake_cluster: Any, full: dict[str, Any]
) -> None:
    from tests.test_api import AUTH

    evict = call(
        "kubernetes_evict_pod", "e", cluster="test", namespace="shop", name="checkout-7d9f-abc"
    )
    acting = {**full, "integrations": [{"name": "kubernetes", "enable_actions": True}]}
    script = [evict, call("TriageReport", "r", **REPORT)]
    with client(settings, fake_cluster, *script, actions=True, acme=acting) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "awaiting_approval")
        c.post(f"/investigations/{tid}/decision", json={"approve": True}, headers=AUTH)
        wait_for(c, tid, "done")
        _, scenario, _ = download(c, tid)
    assert scenario["enable_actions"] is True
    assert scenario["expect"]["allowed_actions"] == [
        {
            "name": "kubernetes_evict_pod",
            "args": {"cluster": "test", "namespace": "shop", "name": "checkout-7d9f-abc"},
        }
    ]


def test_tool_arguments_are_redacted_too(
    settings: Settings, fake_cluster: Any, full: dict[str, Any]
) -> None:
    """The model writes the arguments, and it can copy a secret out of a log."""
    leaky = call(
        "kubernetes_list_pods",
        "l",
        cluster="test",
        namespace="shop",
        label_selector=f"app={SECRET}",
    )
    with client(settings, fake_cluster, leaky, call("TriageReport", "r", **REPORT), acme=full) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        _, scenario, text = download(c, tid)
        page = c.get(f"/console/investigations/{tid}", headers=VIEW).text
    assert SECRET not in page  # stored redacted: the console's tool calls don't show it
    assert SECRET not in text
    assert (
        scenario["tools"]["kubernetes_list_pods"][0]["match"]["label_selector"]
        == "app=token=[REDACTED]"
    )


def test_rows_recorded_before_argument_redaction_are_redacted_on_export() -> None:
    t = Investigation(
        id="old", contract_id="acme", title="t", started=0, status="done", input={"question": "q"}
    )
    old_row = {
        "tool": "kubernetes_list_pods",
        "args": {"label_selector": SECRET},
        "result": "[]",
        "is_error": False,
    }
    approved = {"approve": True, "actions": [{"name": "x", "args": {"note": SECRET}}]}
    assert SECRET not in evals.scenario_yaml(t, make_contract(), [old_row], [])
    t = t.model_copy(update={"kind": "triage", "input": {"status": "firing", "alerts": []}})
    assert SECRET not in evals.scenario_yaml(t, make_contract(), [], [approved])


def test_a_saved_scenario_carries_the_contracts_approved_teachings() -> None:
    t = Investigation(
        id="t1",
        contract_id="acme",
        title="t",
        started=0,
        status="done",
        input={"status": "firing", "alerts": []},
    )
    approved = [{"id": 3, "text": "Never roll back checkout.", "alerts": ["KubePodCrashLooping"]}]
    saved = yaml.safe_load(evals.scenario_yaml(t, make_contract(), [], [], approved))
    assert saved["teachings"] == [
        {"text": "Never roll back checkout.", "alerts": ["KubePodCrashLooping"]}
    ]
    assert "teachings" not in yaml.safe_load(evals.scenario_yaml(t, make_contract(), [], []))


@pytest.mark.anyio
@pytest.mark.parametrize("ok", [True, False])
async def test_a_saved_check_replays_and_scores(
    ok: bool, settings: Settings, fake_cluster: Any, full: dict[str, Any]
) -> None:
    from aiops_agent.store import now
    from tests.test_checks import CHECK, DAY, tick

    ev = [{"source": "kubernetes_list_pods", "finding": "all run"}]
    if ok:
        verdict = call("CheckResult", "v", passed=True, summary="All run.", evidence=ev)
    else:
        verdict = call("CheckResult", "v", passed=False, summary="x", evidence=ev, report=REPORT)
    prompt = f"{CHECK['prompt']} {SECRET}"
    acme = {**full, "checks": [{**CHECK, "prompt": prompt}]}
    with client(settings, fake_cluster, *steps(LIST, last=verdict), acme=acme) as c:
        (tid,) = tick(c, now() + DAY)
        wait_for(c, tid, "done")
        r, scenario, text = download(c, tid)
    assert r.status_code == 200 and SECRET not in text
    assert scenario["check"] == {
        "name": "shop-healthy",
        "prompt": f"{CHECK['prompt']} token=[REDACTED]",
    }
    assert "alert" not in scenario
    if ok:
        assert scenario["expect"] == {
            "passed": True,
            "keywords": [],
            "max_tool_calls": 4,
            "evidence": ["kubernetes_list_pods"],
        }
    else:
        assert scenario["expect"] == {
            "category": [REPORT["category"]],
            "passed": False,
            "keywords": [],
            "max_tool_calls": 4,
        }
    async with replay(settings, scenario, scripted(*steps(LIST, last=verdict))) as a:
        outcome, _ = await evals.check(a, scenario["check"], "k", scenario["expect"])
    assert evals.score_check(scenario, outcome) == []
