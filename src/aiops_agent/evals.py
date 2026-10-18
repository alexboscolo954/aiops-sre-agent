"""Offline evals: run the real agent and a real LLM against recorded tool outputs.

Each scenario (evals/scenarios/*.yaml) holds an alert or a question, the tool
results recorded from a real cluster, and what a correct Report or Answer must
contain. The MCP servers are
the real ones (same tool names and schemas the model sees in production; a
vendor's come from its schema snapshot), but a replay middleware answers every
call from the recording, so no cluster or vendor binary is needed and runs are
repeatable.
"""

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import jsonschema
import yaml
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp.types import TextContent

from aiops_agent import agent, contracts
from aiops_agent.config import Settings
from aiops_agent.contracts import Contract, Integration, Vendor
from aiops_agent.models import AlertGroup, Investigation
from aiops_agent.safety import redact, redact_strings


class Replay(Middleware):
    """Answer tool calls from a recording. A recording is either one result for the
    tool, or a list of {match: {arg: value}, result: ...} tried in order.
    {"error": "..."} replays a tool error. Tools under `passthrough` prefixes
    (runbooks) run for real."""

    def __init__(
        self,
        recordings: dict[str, Any],
        passthrough: tuple[str, ...] = (),
        namespaces: dict[str, list[str]] | None = None,
    ) -> None:
        self.recordings = recordings
        self.passthrough = passthrough
        self.namespaces = namespaces or {}  # cluster -> the Contract's allowlist

    def lookup(self, tool: str, args: dict[str, Any]) -> Any:
        rec = self.recordings.get(tool)
        if isinstance(rec, list) and rec and isinstance(rec[0], dict) and "match" in rec[0]:
            for case in rec:
                if all(args.get(k) == v for k, v in case["match"].items()):
                    return case["result"]
            return None
        return rec

    async def on_call_tool(self, context: MiddlewareContext[Any], call_next: Any) -> Any:
        if context.message.name.startswith(self.passthrough):
            return await call_next(context)
        args = context.message.arguments or {}
        # Validate as the real call would, so a missing or wrong argument (a cluster
        # outside the Contract) costs the model a turn here too.
        assert context.fastmcp_context is not None
        tool = await context.fastmcp_context.fastmcp.get_tool(context.message.name)
        try:
            jsonschema.validate(args, tool.parameters if tool else {})
        except jsonschema.ValidationError as e:
            text = f"Input validation error: {e.message}"
            return ToolResult(content=[TextContent(type="text", text=text)], is_error=True)
        # The real tool's allowlist check, which the recording would otherwise skip:
        # a guessed namespace must fail here too, not return the recorded one's data.
        allowed = self.namespaces.get(args.get("cluster", ""))
        if allowed is not None and "namespace" in args and args["namespace"] not in allowed:
            text = (
                f"namespace {args['namespace']!r} is not allowed in cluster "
                f"{args['cluster']!r}; allowed: {sorted(allowed)}"
            )
            return ToolResult(content=[TextContent(type="text", text=text)], is_error=True)
        found = self.lookup(context.message.name, args)
        if found is None or (isinstance(found, dict) and set(found) == {"error"}):
            text = found["error"] if found else "no recorded data for this call"
            return ToolResult(content=[TextContent(type="text", text=text)], is_error=True)
        # Same shape FastMCP produces: dicts as-is, anything else wrapped in "result".
        structured = found if isinstance(found, dict) else {"result": found}
        text = found if isinstance(found, str) else json.dumps(found)
        return ToolResult(
            content=[TextContent(type="text", text=text)], structured_content=structured
        )


EVAL_CLUSTER = "kind"  # the Scenarios were recorded on the kind demo


def scenario_contract(
    namespace: str,
    enable_actions: bool,
    runbook_dirs: Path | list[Path],
    clusters: dict[str, list[str]] | None = None,
    integrations: list[str | dict[str, Any]] | None = None,
) -> Contract:
    """The Contract a Scenario runs in, offering the same tools production did. A
    saved Scenario names its clusters (with namespaces) and integrations; an older
    one has one cluster, `kind`, with its namespace, and kubernetes plus runbooks.
    Integrations get placeholder config: the replay answers before any real call.
    A vendor is {name, vendor, tools}: its tools come from the vendor's schema
    snapshot, and the Hub's list is the one the Contract had."""
    dirs = [runbook_dirs] if isinstance(runbook_dirs, Path) else runbook_dirs
    built: list[dict[str, Any]] = []
    for name in integrations or ["kubernetes", "runbooks"]:
        if isinstance(name, dict):  # a vendor
            built.append({k: name[k] for k in ("name", "vendor", "tools")})
        elif name == "kubernetes":
            built.append({"name": name, "enable_actions": enable_actions})
        elif name == "prometheus":
            built.append({"name": name, "url": "http://replay.invalid"})  # never reached
        elif name == "runbooks":
            if any(d.is_dir() for d in dirs):
                built.append({"name": name})
        else:  # a vendor saved by name only: which vendor, and its list, are unknown
            raise ValueError(
                f"can't replay integration {name!r}: a vendor needs {{name, vendor, tools}}"
            )
    spaces = {EVAL_CLUSTER: [namespace]} if clusters is None else clusters  # {}: none
    cluster_list = [{"name": c, "context": "replay", "namespaces": ns} for c, ns in spaces.items()]
    data = {"id": "eval", "name": "Eval", "clusters": cluster_list, "integrations": built}
    return contracts.build(data, runbook_dirs=dirs)


def replay_server(
    contract: Contract, settings: Settings, recordings: dict[str, Any]
) -> agent.Toolbox:
    """Real tool definitions and the Hub's real list; the API clients are never reached."""
    apis = {c.name: (MagicMock(), MagicMock()) for c in contract.clusters}
    toolbox = agent.build_mcp(contract, settings, apis, snapshots=True)
    namespaces = {c.name: c.namespaces for c in contract.clusters}
    toolbox.mcp.add_middleware(Replay(recordings, ("runbooks_",), namespaces))
    return toolbox


def allowed(expect: dict[str, Any], action: dict[str, Any]) -> bool:
    """expect.allowed_actions: [{name, args?}], args matched as a subset. Empty by default."""
    return any(
        a["name"] == action["name"]
        and all(action["args"].get(k) == v for k, v in a.get("args", {}).items())
        for a in expect.get("allowed_actions", [])
    )


async def triage(
    a: Any, group: AlertGroup, thread_id: str, expect: dict[str, Any]
) -> tuple[agent.Outcome, list[dict[str, Any]]]:
    """Start a triage. Allowed proposed actions are recorded, rejected (never executed
    against the recording) and resumed so the report still gets scored. A disallowed
    one stops the run and stays pending for score() to fail."""
    outcome, proposed = await agent.start(a, group, thread_id), []
    for _ in range(3):  # ponytail: bounded re-proposals; raise if a scenario needs more
        if not outcome.pending or not all(allowed(expect, p) for p in outcome.pending):
            break
        proposed += outcome.pending
        msg = "Eval: proposal recorded, not executed. Do not retry; finish the report."
        outcome = await agent.resume(
            a, thread_id, [{"type": "reject", "message": msg} for _ in outcome.pending]
        )
    return outcome, proposed


def score(scenario: dict[str, Any], outcome: agent.Outcome) -> list[str]:
    """Return the list of failed checks (empty = pass)."""
    expect, report, failures = scenario["expect"], outcome.report, []
    bad = [p["name"] for p in outcome.pending if not allowed(expect, p)]
    if bad:
        return [f"attempted write action: {bad}"]
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
    return failures + missing_links(expect, report.evidence)


def missing_links(expect: dict[str, Any], evidence: list[Any]) -> list[str]:
    """expect.links: at least this many Evidence links, after the Hub dropped any a
    link tool didn't return."""
    kept = sum(e.link is not None for e in evidence)
    return [f"{kept} evidence links < {expect['links']}"] if kept < expect.get("links", 0) else []


def score_answer(scenario: dict[str, Any], outcome: agent.Outcome) -> list[str]:
    """A Question's checks: keywords in the Answer, the Evidence sources it must cite,
    no cited source that never ran (invented Evidence), and the tool budget."""
    expect, answer, failures = scenario["expect"], outcome.answer, []
    if answer is None:
        return ["no answer"]
    text = answer.answer.lower()
    missing = [k for k in expect.get("keywords", []) if k.lower() not in text]
    if missing:
        failures.append(f"answer misses {missing}")
    cited = {e.source for e in answer.evidence}
    uncited = [t for t in expect.get("evidence", []) if t not in cited]
    if uncited:
        failures.append(f"evidence doesn't cite {uncited}")
    invented = sorted(cited - set(outcome.tool_calls))
    if invented:
        failures.append(f"evidence cites tools that never ran: {invented}")
    if len(outcome.tool_calls) > expect.get("max_tool_calls", 12):
        failures.append(f"{len(outcome.tool_calls)} tool calls > {expect['max_tool_calls']}")
    return failures + missing_links(expect, answer.evidence)


def load_scenarios(directory: Path) -> list[tuple[Path, dict[str, Any]]]:
    return [(p, yaml.safe_load(p.read_text())) for p in sorted(directory.glob("*.yaml"))]


async def run(
    directory: Path, settings: Settings, runbook_dirs: Path | list[Path]
) -> list[dict[str, Any]]:
    results = []
    for path, scenario in load_scenarios(directory):
        contract = scenario_contract(
            scenario.get("namespace", ""),
            scenario.get("enable_actions", False),
            runbook_dirs,
            scenario.get("clusters"),
            scenario.get("integrations"),
        )
        question, thread = scenario.get("question"), f"eval-{path.stem}"
        start = time.monotonic()
        try:
            async with agent.open_agent(
                settings,
                replay_server(contract, settings, scenario["tools"]),
                kind="question" if question else "triage",
            ) as a:
                if question:
                    outcome, proposed = await agent.ask(a, question, thread), list[dict[str, Any]]()
                    failures = score_answer(scenario, outcome)
                else:
                    group = AlertGroup.model_validate(scenario["alert"])
                    outcome, proposed = await triage(a, group, thread, scenario["expect"])
                    failures = score(scenario, outcome)
            calls, report, answer = outcome.tool_calls, outcome.report, outcome.answer
            dropped = outcome.dropped_links
        except agent.TriageError as e:
            failures, calls, report, answer, proposed, dropped = [str(e)], [], None, None, [], 0
        results.append(
            {
                "scenario": path.stem,
                "passed": not failures,
                "failures": failures,
                "category": report.category if report else None,
                "tool_calls": len(calls),
                "seconds": round(time.monotonic() - start, 1),
                "calls": calls,
                "proposed": [p["name"] for p in proposed],
                "dropped_links": dropped,
                "report": report.to_markdown() if report else None,
                **({"answer": answer.to_markdown()} if answer else {}),
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


def _result(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text


def integration(i: Integration) -> str | dict[str, Any]:
    """A builtin by name; a vendor with what replay needs: which vendor (for its
    schema snapshot) and the Hub's list. Never its env, secrets or probe."""
    if isinstance(i, Vendor):
        return {"name": i.name, "vendor": i.vendor, "tools": dict(i.tools)}
    return i.name


def scenario_yaml(
    t: Investigation,
    contract: Contract,
    tool_calls: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> str:
    """A finished Investigation as a draft Scenario: what started it, every recorded
    tool result (already redacted when recorded), and an Expectation to edit. Replay
    passes Runbook tools through to the real files, so they aren't recorded here.
    Known limits: a call made twice with different results replays the first; a
    replayed call must pass every argument the recording did; and the text is the
    same content but not byte for byte the same JSON."""
    assert t.input is not None and t.status == "done"
    tools: dict[str, list[dict[str, Any]]] = {}
    for call in tool_calls:
        if call["tool"].startswith("runbooks_"):
            continue
        result = {"error": call["result"]} if call["is_error"] else _result(call["result"])
        # Arguments are redacted when recorded; again here for rows from before that.
        match = redact_strings(call["args"])
        tools.setdefault(call["tool"], []).append({"match": match, "result": result})
    approved = [a for d in decisions if d["approve"] for a in d["actions"]]
    budget = len(tool_calls) + 3
    body: dict[str, Any] = {
        "description": redact(f"Saved from {t.kind} {t.id} ({t.contract_id}): {t.title}"),
        "clusters": {c.name: sorted(c.namespaces) for c in contract.clusters},
        "integrations": [integration(i) for i in contract.integrations],
    }
    if t.kind == "question":
        body["question"] = redact_strings(t.input["question"])
        cited = sorted({e.source for e in t.answer.evidence}) if t.answer else []
        body["expect"] = {"keywords": [], "evidence": cited, "max_tool_calls": budget}
    else:
        body["alert"] = redact_strings(t.input)
        category = [t.report.category] if t.report else []
        body["expect"] = {"category": category, "keywords": [], "max_tool_calls": budget}
        if approved:
            body["enable_actions"] = True
            body["expect"]["allowed_actions"] = [
                {"name": a["name"], "args": redact_strings(a["args"])} for a in approved
            ]
    body["tools"] = tools
    day = datetime.fromtimestamp(t.started, UTC).strftime("%Y-%m-%d")
    header = (
        f"# Draft Scenario from {t.kind} {t.id} ({t.contract_id}), {day}.\n"
        "# Before committing it to <contracts-repo>/" + t.contract_id + "/scenarios/:\n"
        "# add the keywords a correct result must contain, and check the category,\n"
        "# evidence, budget and allowed actions. A Question with follow-ups keeps only\n"
        "# its first question, but every call, so its budget reads high.\n"
    )
    return header + yaml.safe_dump(body, sort_keys=False, width=100, allow_unicode=True)
