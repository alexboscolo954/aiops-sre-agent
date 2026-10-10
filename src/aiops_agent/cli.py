"""Command line: `aiops triage`, `aiops serve`, `aiops mcp`, `aiops eval`."""

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from aiops_agent import agent, evals
from aiops_agent.config import Settings
from aiops_agent.models import AlertGroup


def ask(action: dict[str, Any], auto_reject: bool) -> dict[str, Any]:
    print(f"\n>>> {action['description']}", file=sys.stderr)
    if auto_reject or not sys.stdin.isatty():
        print(">>> rejected (non-interactive)", file=sys.stderr)
        return {"type": "reject", "message": "No human available to approve. Report only."}
    answer = input(">>> approve? [y/N] ").strip().lower()
    if answer == "y":
        return {"type": "approve"}
    return {"type": "reject", "message": "Rejected by the on-call engineer. Do not retry."}


async def triage(group: AlertGroup, as_json: bool, auto_reject: bool) -> int:
    settings = Settings()
    async with agent.open_agent(settings) as a:
        outcome = await agent.start(a, group, thread_id=str(uuid.uuid4()))
        while outcome.pending:
            decisions = [ask(action, auto_reject) for action in outcome.pending]
            outcome = await agent.resume(a, outcome.thread_id, decisions)
    assert outcome.report is not None
    if as_json:
        print(outcome.report.model_dump_json(indent=2))
    else:
        print(outcome.report.to_markdown())
        print(f"\n_tool calls: {', '.join(outcome.tool_calls)}_", file=sys.stderr)
    return 0


def run_mcp(name: str, transport: str, host: str, port: int) -> int:
    from aiops_agent.servers import kubernetes, prometheus, runbooks

    builders = {"kubernetes": kubernetes, "prometheus": prometheus, "runbooks": runbooks}
    server = builders[name].build_server(Settings())
    if transport == "stdio":
        server.run(transport="stdio", show_banner=False)
    else:
        server.run(transport="http", host=host, port=port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aiops", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("triage", help="triage one Alertmanager webhook payload (JSON file)")
    t.add_argument("alert", type=Path)
    t.add_argument("--json", action="store_true", help="print the report as JSON")
    t.add_argument("--auto-reject", action="store_true", help="reject every action, report only")

    s = sub.add_parser("serve", help="run the Alertmanager webhook receiver")
    s.add_argument("--host", default="0.0.0.0")  # noqa: S104 - container entrypoint
    s.add_argument("--port", type=int, default=8080)

    m = sub.add_parser("mcp", help="run one MCP server standalone (e.g. for Claude Code)")
    m.add_argument("server", choices=["kubernetes", "prometheus", "runbooks"])
    m.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    m.add_argument("--host", default="127.0.0.1")
    m.add_argument("--port", type=int, default=8765)

    e = sub.add_parser("eval", help="score the agent on recorded scenarios")
    e.add_argument("scenarios", type=Path, nargs="?", default=Path("evals/scenarios"))
    e.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "triage":
        group = AlertGroup.model_validate_json(args.alert.read_text())
        return asyncio.run(triage(group, args.json, args.auto_reject))
    if args.cmd == "mcp":
        return run_mcp(args.server, args.transport, args.host, args.port)
    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("aiops_agent.api:create_app", factory=True, host=args.host, port=args.port)
        return 0
    if args.cmd == "eval":
        results = asyncio.run(evals.run(args.scenarios, Settings()))
        print(json.dumps(results, indent=2) if args.json else evals.table(results))
        return 0 if all(r["passed"] for r in results) else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
