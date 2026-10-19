from pathlib import Path
from typing import Any

import pytest
import yaml

from aiops_agent import agent, evals
from aiops_agent.config import Settings
from aiops_agent.models import AlertGroup
from tests.conftest import REPORT, call, scripted

SCENARIOS = Path(__file__).parent.parent / "evals" / "scenarios"


def replay(settings: Settings, recordings: dict[str, Any], actions: bool = False) -> agent.Toolbox:
    contract = evals.scenario_contract("shop", actions, Path("no-runbooks"))
    return evals.replay_server(contract, settings, recordings)


def test_replay_matches_args_in_order() -> None:
    r = evals.Replay(
        {"t": [{"match": {"previous": True}, "result": "crash"}, {"match": {}, "result": "fine"}]}
    )
    assert r.lookup("t", {"previous": True}) == "crash"
    assert r.lookup("t", {"previous": False}) == "fine"
    assert r.lookup("missing", {}) is None


@pytest.mark.anyio
async def test_replay_server_feeds_the_agent(settings: Settings) -> None:
    recordings = {"kubernetes_pod_logs": "java.lang.OutOfMemoryError: Java heap space"}
    model = scripted(
        call(
            "kubernetes_pod_logs", "c1", cluster="kind", namespace="shop", name="p", previous=True
        ),
        call("TriageReport", "c2", **REPORT),
    )
    group = AlertGroup.model_validate({"status": "firing", "alerts": []})
    async with agent.open_agent(settings, replay(settings, recordings), model) as a:
        outcome = await agent.start(a, group, "e1")
    scenario: dict[str, Any] = {"expect": {"category": ["resource_limits"], "keywords": ["memory"]}}
    assert evals.score(scenario, outcome) == []
    scenario["expect"]["keywords"] = ["DATABASE_URL"]
    assert evals.score(scenario, outcome) == ["root cause misses ['DATABASE_URL']"]


@pytest.mark.anyio
async def test_replay_validates_arguments_like_the_real_call(settings: Settings) -> None:
    from fastmcp import Client

    tb = replay(settings, {"kubernetes_list_pods": []})
    async with Client(tb.mcp) as c:
        ok = await c.call_tool("kubernetes_list_pods", {"cluster": "kind", "namespace": "shop"})
        bad = await c.call_tool(
            "kubernetes_list_pods", {"cluster": "prod", "namespace": "shop"}, raise_on_error=False
        )
        missing = await c.call_tool(
            "kubernetes_list_pods", {"namespace": "shop"}, raise_on_error=False
        )
    assert not ok.is_error
    assert bad.is_error and "'prod' is not one of ['kind']" in bad.content[0].text
    assert missing.is_error and "'cluster' is a required property" in missing.content[0].text
    async with Client(tb.mcp) as c:  # a guessed namespace fails, as the real tool does
        guessed = await c.call_tool(
            "kubernetes_list_pods",
            {"cluster": "kind", "namespace": "default"},
            raise_on_error=False,
        )
    assert guessed.is_error
    assert guessed.content[0].text == (
        "namespace 'default' is not allowed in cluster 'kind'; allowed: ['shop']"
    )


@pytest.mark.anyio
async def test_allowed_proposal_is_rejected_and_scored(settings: Settings) -> None:
    recordings = {"kubernetes_evict_pod": "evicted"}
    group = AlertGroup.model_validate({"status": "firing", "alerts": []})
    evict = call("kubernetes_evict_pod", "c1", cluster="kind", namespace="shop", name="p")
    scenario: dict[str, Any] = {"expect": {"category": ["resource_limits"]}}

    model = scripted(evict, call("TriageReport", "c2", **REPORT))
    async with agent.open_agent(settings, replay(settings, recordings, actions=True), model) as a:
        outcome, proposed = await evals.triage(a, group, "e2", scenario["expect"])
    assert proposed == [] and evals.score(scenario, outcome) == [
        "attempted write action: ['kubernetes_evict_pod']"
    ]

    scenario["expect"]["allowed_actions"] = [
        {"name": "kubernetes_evict_pod", "args": {"namespace": "shop"}}
    ]
    model = scripted(evict, call("TriageReport", "c2", **REPORT))
    async with agent.open_agent(settings, replay(settings, recordings, actions=True), model) as a:
        outcome, proposed = await evals.triage(a, group, "e3", scenario["expect"])
    assert [p["name"] for p in proposed] == ["kubernetes_evict_pod"]
    assert outcome.executed_actions == []  # rejected, never ran
    assert evals.score(scenario, outcome) == []

    scenario["expect"]["allowed_actions"][0]["args"] = {"namespace": "other"}
    assert not evals.allowed(scenario["expect"], proposed[0])


@pytest.mark.parametrize("path", sorted(SCENARIOS.glob("*.yaml")), ids=lambda p: p.stem)
def test_scenarios_are_well_formed(path: Path, settings: Settings) -> None:
    s = yaml.safe_load(path.read_text())
    assert s["tools"] and ("namespace" in s or "clusters" in s)  # clusters {}: none
    # Every recording answers a tool the Scenario's Contract offers (a vendor's from
    # its snapshot): a renamed or unlisted tool would never be called.
    contract = evals.scenario_contract(
        s.get("namespace", ""),
        s.get("enable_actions", False),
        [Path("no-runbooks")],
        s.get("clusters"),
        s.get("integrations"),
    )
    assert set(s["tools"]) <= set(evals.replay_server(contract, settings, {}).access)
    if "question" in s:  # an Answer: keywords and the Evidence it must cite
        assert "alert" not in s and s["question"].strip() and s["expect"]["keywords"]
        for source in s["expect"]["evidence"]:
            assert ({source} if isinstance(source, str) else set(source)) <= set(s["tools"])
    else:
        AlertGroup.model_validate(s["alert"])
        assert s["expect"]["category"]


@pytest.mark.anyio
async def test_an_answer_is_scored_on_keywords_and_real_evidence(settings: Settings) -> None:
    recordings = {"kubernetes_list_pods": [{"name": "checkout-1", "restarts": 4}]}
    answer = {
        "answer": "checkout-1 restarted 4 times.",
        "evidence": [{"source": "kubernetes_list_pods", "finding": "checkout-1 restarts 4"}],
    }
    model = scripted(
        call("kubernetes_list_pods", "c1", cluster="kind", namespace="shop"),
        call("Answer", "c2", **answer),
    )
    async with agent.open_agent(
        settings, replay(settings, recordings), model, kind="question"
    ) as a:
        outcome = await agent.ask(a, "Is checkout healthy?", "q1")
    expect: dict[str, Any] = {"keywords": ["checkout"], "evidence": ["kubernetes_list_pods"]}
    assert evals.score_answer({"expect": expect}, outcome) == []
    expect["evidence"] = [["kubernetes_pod_logs", "kubernetes_list_pods"]]  # any of them
    assert evals.score_answer({"expect": expect}, outcome) == []

    expect.update(keywords=["reports"], evidence=["kubernetes_pod_logs"], max_tool_calls=0)
    assert evals.score_answer({"expect": expect}, outcome) == [
        "answer misses ['reports']",
        "evidence doesn't cite ['kubernetes_pod_logs']",
        "2 tool calls > 0",  # the scripted Answer counts, like TriageReport
    ]
    assert outcome.answer is not None
    outcome.answer.evidence.append(outcome.answer.evidence[0].model_copy(update={"source": "x"}))
    assert "evidence cites tools that never ran: ['x']" in evals.score_answer(
        {"expect": {}}, outcome
    )
    assert evals.score_answer({"expect": {}}, agent.Outcome("t")) == ["no answer"]
