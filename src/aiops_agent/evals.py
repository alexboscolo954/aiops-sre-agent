"""Offline evals: run the real agent and a real LLM against recorded tool outputs.

Each scenario (evals/scenarios/*.yaml) holds an alert, the tool results recorded
from a real cluster, and what a correct triage must contain. The MCP servers are
the real ones (same tool names and schemas the model sees in production), but a
replay middleware answers every call from the recording, so no cluster is needed
and runs are repeatable.
"""

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import yaml
from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp.types import TextContent

from aiops_agent import agent
from aiops_agent.config import Settings
from aiops_agent.models import AlertGroup
from aiops_agent.servers import kubernetes, runbooks


class Replay(Middleware):
    """Answer tool calls from a recording. A recording is either one result for the
    tool, or a list of {match: {arg: value}, result: ...} tried in order."""

    def __init__(self, recordings: dict[str, Any]) -> None:
        self.recordings = recordings

    def lookup(self, tool: str, args: dict[str, Any]) -> Any:
        rec = self.recordings.get(tool)
        if isinstance(rec, list) and rec and isinstance(rec[0], dict) and "match" in rec[0]:
            for case in rec:
                if all(args.get(k) == v for k, v in case["match"].items()):
                    return case["result"]
            return None
        return rec

    async def on_call_tool(self, context: MiddlewareContext[Any], call_next: Any) -> Any:
        found = self.lookup(context.message.name, context.message.arguments or {})
        if found is None:
            text = "no recorded data for this call"
            return ToolResult(content=[TextContent(type="text", text=text)], is_error=True)
        # Same shape FastMCP produces: dicts as-is, anything else wrapped in "result".
        structured = found if isinstance(found, dict) else {"result": found}
        text = found if isinstance(found, str) else json.dumps(found)
        return ToolResult(
            content=[TextContent(type="text", text=text)], structured_content=structured
        )


def replay_server(settings: Settings, recordings: dict[str, Any]) -> FastMCP:
    root = FastMCP("aiops-replay")
    # Real tool definitions; the API clients are never reached.
    root.mount(kubernetes.build_server(settings, MagicMock(), MagicMock()), namespace="kubernetes")
    if settings.runbooks_dir.is_dir():
        root.mount(runbooks.build_server(settings), namespace="runbooks")
    root.add_middleware(Replay(recordings))
    return root


def score(scenario: dict[str, Any], outcome: agent.Outcome) -> list[str]:
    """Return the list of failed checks (empty = pass)."""
    expect, report, failures = scenario["expect"], outcome.report, []
    if report is None:
        return ["no report"]
    if report.category not in expect["category"]:
        failures.append(f"category {report.category} not in {expect['category']}")
    text = f"{report.summary} {report.probable_root_cause}".lower()
    missing = [k for k in expect.get("keywords", []) if k.lower() not in text]
    if missing:
        failures.append(f"root cause misses {missing}")
    if len(outcome.tool_calls) > expect.get("max_tool_calls", 12):
        failures.append(f"{len(outcome.tool_calls)} tool calls > {expect['max_tool_calls']}")
    return failures


def load_scenarios(directory: Path) -> list[tuple[Path, dict[str, Any]]]:
    return [(p, yaml.safe_load(p.read_text())) for p in sorted(directory.glob("*.yaml"))]


async def run(directory: Path, settings: Settings) -> list[dict[str, Any]]:
    results = []
    for path, scenario in load_scenarios(directory):
        s = settings.model_copy(
            update={"namespaces": [scenario["namespace"]], "kube_context": "replay"}
        )
        group = AlertGroup.model_validate(scenario["alert"])
        start = time.monotonic()
        try:
            async with agent.open_agent(s, mcp=replay_server(s, scenario["tools"])) as a:
                outcome = await agent.start(a, group, f"eval-{path.stem}")
            failures = score(scenario, outcome)
            calls, category = outcome.tool_calls, outcome.report and outcome.report.category
        except agent.TriageError as e:
            failures, calls, category = [str(e)], [], None
        results.append(
            {
                "scenario": path.stem,
                "passed": not failures,
                "failures": failures,
                "category": category,
                "tool_calls": len(calls),
                "seconds": round(time.monotonic() - start, 1),
            }
        )
    return results


def table(results: list[dict[str, Any]]) -> str:
    rows = [f"{'scenario':32} {'result':6} {'calls':>5} {'secs':>5}  notes"]
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        notes = "; ".join(r["failures"]) or str(r["category"])
        rows.append(f"{r['scenario']:32} {mark:6} {r['tool_calls']:>5} {r['seconds']:>5}  {notes}")
    passed = sum(r["passed"] for r in results)
    rows.append(f"\n{passed}/{len(results)} passed")
    return "\n".join(rows)
