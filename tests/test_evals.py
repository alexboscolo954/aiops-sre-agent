from pathlib import Path
from typing import Any

import pytest
import yaml

from aiops_agent import agent, evals
from aiops_agent.config import Settings
from aiops_agent.models import AlertGroup
from tests.conftest import REPORT, call, scripted

SCENARIOS = Path(__file__).parent.parent / "evals" / "scenarios"


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
        call("kubernetes_pod_logs", "c1", namespace="shop", name="p", previous=True),
        call("TriageReport", "c2", **REPORT),
    )
    group = AlertGroup.model_validate({"status": "firing", "alerts": []})
    async with agent.open_agent(
        settings, model, mcp=evals.replay_server(settings, recordings)
    ) as a:
        outcome = await agent.start(a, group, "e1")
    scenario: dict[str, Any] = {"expect": {"category": ["resource_limits"], "keywords": ["memory"]}}
    assert evals.score(scenario, outcome) == []
    scenario["expect"]["keywords"] = ["DATABASE_URL"]
    assert evals.score(scenario, outcome) == ["root cause misses ['DATABASE_URL']"]


@pytest.mark.parametrize("path", sorted(SCENARIOS.glob("*.yaml")), ids=lambda p: p.stem)
def test_scenarios_are_well_formed(path: Path) -> None:
    s = yaml.safe_load(path.read_text())
    AlertGroup.model_validate(s["alert"])
    assert s["expect"]["category"] and s["tools"] and s["namespace"]
