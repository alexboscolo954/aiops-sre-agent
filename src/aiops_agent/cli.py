"""Command line: `aiops triage`, `aiops serve`, `aiops mcp`, `aiops eval`, `aiops contracts`,
`aiops integrations`, `aiops incidents`, `aiops sizing`."""

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from aiops_agent import agent, contracts, embeddings, evals, sizing, usage
from aiops_agent.config import Settings, refuse_moved
from aiops_agent.models import AlertGroup
from aiops_agent.servers import vendors
from aiops_agent.store import Store, connect


def ask(action: dict[str, Any], auto_reject: bool) -> dict[str, Any]:
    print(f"\n>>> {action['description']}", file=sys.stderr)
    if auto_reject or not sys.stdin.isatty():
        print(">>> rejected (non-interactive)", file=sys.stderr)
        return {"type": "reject", "message": "No human available to approve. Report only."}
    answer = input(">>> approve? [y/N] ").strip().lower()
    if answer == "y":
        return {"type": "approve"}
    return {"type": "reject", "message": "Rejected by the on-call engineer. Do not retry."}


def contract(settings: Settings, contract_id: str) -> contracts.Contract:
    """One Contract from AIOPS_CONTRACTS_DIR, with its secrets decrypted."""
    refuse_moved()
    if not settings.contracts_dir:
        raise SystemExit("set AIOPS_CONTRACTS_DIR")
    loaded = contracts.load(settings.contracts_dir)
    if contract_id not in loaded:
        raise SystemExit(f"no Contract {contract_id!r}; have: {', '.join(sorted(loaded))}")
    return loaded[contract_id]


async def triage(group: AlertGroup, contract_id: str, as_json: bool, auto_reject: bool) -> int:
    settings = Settings()
    c = contract(settings, contract_id)
    toolbox = agent.build_mcp(c, settings)
    model = agent.build_model(agent.for_contract(settings, c))
    async with agent.open_agent(settings, toolbox, model) as a:
        outcome = await agent.start(a, group, thread_id=str(uuid.uuid4()))
        while outcome.pending:
            decisions = [ask(action, auto_reject) for action in outcome.pending]
            outcome = await agent.resume(a, outcome.thread_id, decisions)
    assert outcome.report is not None
    if as_json:
        report = outcome.report.model_dump(mode="json")
        print(json.dumps({**report, "executed_actions": outcome.executed_actions}, indent=2))
    else:
        print(outcome.report.to_markdown(outcome.executed_actions))
        print(f"\n_tool calls: {', '.join(outcome.tool_calls)}_", file=sys.stderr)
    return 0


def run_mcp(name: str, contract_id: str, transport: str, host: str, port: int) -> int:
    settings = Settings()
    c = contract(settings, contract_id)
    by_name = {i.name: i for i in c.integrations}
    if name not in by_name:
        print(f"Contract {contract_id!r} has no {name} integration", file=sys.stderr)
        return 1
    server, _ = agent.integration_server(c, by_name[name], settings)
    if transport == "stdio":
        server.run(transport="stdio", show_banner=False)
    else:
        server.run(transport="http", host=host, port=port)
    return 0


def validate_contracts(directory: Path) -> int:
    try:
        loaded = contracts.load(directory)
    except contracts.ContractError as e:
        print("\n".join(e.problems), file=sys.stderr)
        return 1
    for c in loaded.values():
        integrations = ", ".join(i.name for i in c.integrations)
        clusters = ", ".join(cl.name for cl in c.clusters) or "-"
        secrets = len(c.secret_refs())
        checks = ", ".join(k.name for k in c.checks) or "-"
        print(
            f"{c.id}: clusters {clusters}; integrations {integrations}; checks {checks}; "
            f"secrets {secrets}"
        )
    return 0


def window_seconds(text: str) -> int:
    """`90m`, `6h`, `7d` in seconds."""
    try:
        return contracts.duration_s(text)
    except ValueError as e:
        raise SystemExit(f"window {e}") from None


def collect_usage(
    c: contracts.Contract, windows: list[int]
) -> tuple[dict[int, list[tuple[str, usage.ContainerUsage]]], int]:
    """Every cluster's container usage over each window, (cluster, usage) pairs per
    window, and an exit status. Missing metrics and Workload-less pods are named on
    stderr, for the longest window."""
    from kubernetes import client as k

    from aiops_agent.servers import kubernetes

    status = 0
    out: dict[int, list[tuple[str, usage.ContainerUsage]]] = {w: [] for w in windows}
    targets = usage.targets(c)
    if not targets:
        print(f"{c.id}: no cluster has a Prometheus (prometheus integration or prometheus_url)")
        return out, 1
    for t in targets:
        cluster = next(cl for cl in c.clusters if cl.name == t.cluster)

        def from_api(cl: contracts.Cluster = cluster, t: usage.Target = t) -> Any:
            api = kubernetes.api_client(cl, c)
            return usage.owners_from_api(
                k.CoreV1Api(api), k.AppsV1Api(api), k.BatchV1Api(api), t.namespaces
            )

        prom = usage.Prom(t)
        try:
            t, missing = usage.check(prom, t)
            # ponytail: each window queried in full (a 7d and a 14d policy read the 14d
            # range twice), so a policy's OOM kills, throttling and step are its own
            by_window = {w: usage.usage(prom, t, w, fallback=from_api) for w in windows}
        except usage.UsageError as e:
            print(f"{c.id}/{t.cluster}: {e}", file=sys.stderr)
            status = 1
            continue
        for w, found in by_window.items():
            rows = sorted(
                found.rows, key=lambda r: (r.workload.namespace, r.workload.name, r.container)
            )
            out[w] += [(t.cluster, r) for r in rows]
        found = by_window[windows[-1]]
        for metric, what in missing.items():
            level = "missing" if metric in usage.REQUIRED else "optional, missing"
            print(f"{c.id}/{t.cluster}: {level}: {metric} ({what})", file=sys.stderr)
        if found.fallback_error:
            print(f"{c.id}/{t.cluster}: Kubernetes API: {found.fallback_error}", file=sys.stderr)
        if found.unknown:
            print(f"{c.id}/{t.cluster}: no Workload for {len(found.unknown)} pods", file=sys.stderr)
    return out, status


def _name(cluster: str, r: usage.ContainerUsage | sizing.Sizing) -> str:
    w = r.workload
    return f"{cluster}/{w.namespace}/{w.kind}/{w.name}/{r.container}"


def sizing_usage(contract_id: str, window: str, as_json: bool) -> int:
    """Every Workload container's usage over the window, per cluster, read-only: what
    Sizings are computed from (slice 9.1). Missing metrics are named, never guessed."""
    seconds = window_seconds(window)
    by_window, status = collect_usage(contract(Settings(), contract_id), [seconds])
    found = by_window[seconds]
    out = [
        {
            "workload": _name(cluster, r),
            "pods": len(r.pods),
            "samples": len(r.cpu),
            "cpu_max": round(max(v for _, v in r.cpu), 4) if r.cpu else None,
            "memory_max_mib": round(max(v for _, v in r.memory) / 2**20, 1) if r.memory else None,
            "requests": r.requests,
            "limits": r.limits,
            "oom_killed_pods": r.oom_killed_pods,
            "throttled": None if r.throttled is None else round(r.throttled, 3),
        }
        for cluster, r in found
    ]
    if as_json:
        print(json.dumps(out, indent=2))
    for row in [] if as_json else out:
        print(
            f"{row['workload']}: {row['pods']} pods, {row['samples']} samples, cpu max "
            f"{row['cpu_max']}, memory max {row['memory_max_mib']} MiB, requests "
            f"{row['requests']}, OOM-killed pods {row['oom_killed_pods']}, throttled "
            f"{row['throttled']}"
        )
    return status


def sizing_show(contract_id: str, as_json: bool) -> int:
    """Every Workload container's Sizing under its Sizing policy (slices 9.2, 9.3),
    read-only: nothing is applied. A container under `off` is listed as excluded."""
    import time

    c = contract(Settings(), contract_id)
    by_window, status = collect_usage(c, c.sizing.windows())
    now = time.time()
    rows: dict[str, dict[str, Any]] = {}
    for window, found in by_window.items():
        for cluster, u in found:
            w = u.workload
            name = c.sizing.policy_for(cluster, w.namespace, w.kind, w.name, u.container)
            policy = c.sizing.policy(name)
            if policy is None:
                rows[_name(cluster, u)] = {
                    "workload": _name(cluster, u), "policy": name, "state": "excluded"
                }  # fmt: skip
                continue
            if policy.window != window:
                continue
            s = sizing.size(u, now, policy)
            row: dict[str, Any] = {
                "workload": _name(cluster, s),
                "policy": name,
                "state": s.state,
                "history_h": round(s.history_s / 3600, 1),
                "needs_h": round(policy.history / 3600, 1),
                "window_h": round(window / 3600, 1),
            }
            for res_name, res in (("cpu", s.cpu), ("memory", s.memory)):
                if res:
                    row[res_name] = {
                        "action": res.action,
                        "current": res.current,
                        "target": res.target,
                        "basis": res.basis,
                    }
            row["risks"] = s.risks
            rows[row["workload"]] = row
    out = [rows[k] for k in sorted(rows)]
    if as_json:
        print(json.dumps(out, indent=2))
        return status
    for row in out:
        head = f"{row['workload']} ({row['policy']})"
        if row["state"] == "excluded":
            print(f"{head}: excluded")
            continue
        if row["state"] == "learning":
            print(f"{head}: learning ({row['history_h']:g} h of {row['needs_h']:g} h)")
            continue
        parts = []
        for res_name in ("cpu", "memory"):
            if res_name in row:
                r = row[res_name]
                now_s = "unset" if r["current"] is None else sizing.show(res_name, r["current"])
                target = sizing.show(res_name, r["target"])
                parts.append(f"{res_name} {r['action']} {now_s} -> {target}")
        days, of = row["history_h"] / 24, row["window_h"] / 24
        short = f" | history {days:.1f}d of {of:g}d" if round(days, 1) < of else ""
        risks = f" | risk: {'; '.join(row['risks'])}" if row["risks"] else ""
        print(f"{head}: {', '.join(parts)}{short}{risks}")
    return status


def snapshot(vendor: str, check: bool, out: str | None = None) -> int:
    """Save the pinned vendor's tool schemas, or with check, fail if they drifted.
    out "-": print it instead (from the image, where the pinned binary is)."""
    if not check:
        text = asyncio.run(vendors.capture(vendors.VENDORS[vendor]))
        if out == "-":
            print(text, end="")
            return 0
        path = Path(out) if out else vendors.SNAPSHOTS / f"{vendor}.json"
        path.write_text(text)
        print(f"wrote {path}", file=sys.stderr)
        return 0
    diff = asyncio.run(vendors.drift(vendor))
    if not diff:
        print(f"{vendor}: snapshot matches")
        return 0
    print(diff, end="")
    print(
        f"\n{vendor}'s tools changed. Regenerate the snapshot (`make snapshots` runs "
        f"`aiops integrations snapshot {vendor}` in the image, where the pinned binary is), "
        "check the Contracts' tool lists and the Scenarios still fit, and commit it.",
        file=sys.stderr,
    )
    return 1


async def embed_past(settings: Settings) -> int:
    """Embed every finished Triage Report that has no embedding by the current model
    yet, for each Contract that searches by meaning."""
    refuse_moved()
    if not (settings.contracts_dir and settings.database_url and settings.embedding_model):
        raise SystemExit("set AIOPS_CONTRACTS_DIR, AIOPS_DATABASE_URL and AIOPS_EMBEDDING_MODEL")
    loaded = contracts.load(settings.contracts_dir)
    failed = 0
    async with connect(settings.database_url.get_secret_value()) as pool:
        store = Store(pool)
        await store.migrate()
        for c in loaded.values():
            embedder = embeddings.for_contract(settings, store, c)
            if embedder is None:
                print(f"{c.id}: off (no incidents integration, or embeddings: false)")
                continue
            rows = await store.unembedded(c.id, embedder.model)
            done = sum([await embedder.index(r) for r in rows])
            failed += len(rows) - done
            print(f"{c.id}: {done} of {len(rows)} Reports embedded")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aiops", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("triage", help="triage one Alertmanager webhook payload (JSON file)")
    t.add_argument("alert", type=Path)
    t.add_argument("--contract", required=True, help="which Contract the alert belongs to")
    t.add_argument("--json", action="store_true", help="print the report as JSON")
    t.add_argument("--auto-reject", action="store_true", help="reject every action, report only")

    s = sub.add_parser("serve", help="run the Alertmanager webhook receiver")
    s.add_argument("--host", default="0.0.0.0")  # noqa: S104 - container entrypoint
    s.add_argument("--port", type=int, default=8080)

    m = sub.add_parser("mcp", help="run one MCP server standalone (e.g. for Claude Code)")
    m.add_argument("server", choices=["kubernetes", "prometheus", "runbooks", "jira"])
    m.add_argument("--contract", required=True, help="serve this Contract's integration")
    m.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    m.add_argument("--host", default="127.0.0.1")
    m.add_argument("--port", type=int, default=8765)

    e = sub.add_parser("eval", help="score the agent on recorded scenarios")
    e.add_argument("scenarios", type=Path, nargs="?", default=Path("evals/scenarios"))
    e.add_argument("--json", action="store_true")
    e.add_argument("--out", type=Path, help="write each report as markdown here")
    e.add_argument(
        "--runbooks",
        type=Path,
        action="append",
        help="runbook folder to replay (repeat: shared/runbooks, then the Contract's own, "
        "which wins a name clash); "
        "default ./runbooks",
    )

    c = sub.add_parser("contracts", help="manage the contracts directory")
    csub = c.add_subparsers(dest="contracts_cmd", required=True)
    v = csub.add_parser("validate", help="check every Contract and decrypt its secrets")
    v.add_argument("directory", type=Path)
    csub.add_parser("new-token", help="a webhook token for a Contract's Alertmanager")

    i = sub.add_parser("integrations", help="vendor MCP servers in the Hub's registry")
    isub = i.add_subparsers(dest="integrations_cmd", required=True)
    snap = isub.add_parser("snapshot", help="save a vendor's tool schemas for replay")
    snap.add_argument("vendor", choices=sorted(vendors.VENDORS))
    snap.add_argument("--check", action="store_true", help="fail if the vendor's tools drifted")
    snap.add_argument("--out", help="write here instead of the package's snapshots/; - prints")

    n = sub.add_parser("incidents", help="the Contracts' past Reports in the Hub's database")
    nsub = n.add_subparsers(dest="incidents_cmd", required=True)
    nsub.add_parser("embed", help="embed past Reports for search by meaning (once, after setup)")

    z = sub.add_parser("sizing", help="Workload usage and Sizings, read-only")
    zsub = z.add_subparsers(dest="sizing_cmd", required=True)
    zu = zsub.add_parser("usage", help="every Workload container's usage, from Prometheus")
    zu.add_argument("--contract", required=True, help="a Contract id in AIOPS_CONTRACTS_DIR")
    zu.add_argument("--window", default="7d", help="how far back: 90m, 6h, 7d (default 7d)")
    zu.add_argument("--json", action="store_true")
    zs = zsub.add_parser("show", help="every Workload container's Sizing; nothing is applied")
    zs.add_argument("--contract", required=True, help="a Contract id in AIOPS_CONTRACTS_DIR")
    zs.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "sizing":
        if args.sizing_cmd == "show":
            return sizing_show(args.contract, args.json)
        return sizing_usage(args.contract, args.window, args.json)
    if args.cmd == "incidents":
        return asyncio.run(embed_past(Settings()))
    if args.cmd == "integrations":
        return snapshot(args.vendor, args.check, args.out)
    if args.cmd == "contracts" and args.contracts_cmd == "new-token":
        token, digest = contracts.new_token()
        print(f"token (give it to the Contract's Alertmanager, shown once): {token}")
        print(f"contract.yaml:  webhook_token_sha256: {digest}")
        return 0
    if args.cmd == "contracts":
        return validate_contracts(args.directory)
    if args.cmd == "triage":
        group = AlertGroup.model_validate_json(args.alert.read_text())
        return asyncio.run(triage(group, args.contract, args.json, args.auto_reject))
    if args.cmd == "mcp":
        return run_mcp(args.server, args.contract, args.transport, args.host, args.port)
    if args.cmd == "serve":
        import uvicorn

        refuse_moved()
        uvicorn.run("aiops_agent.api:create_app", factory=True, host=args.host, port=args.port)
        return 0
    if args.cmd == "eval":
        runbooks = args.runbooks or [Path("runbooks")]
        results = asyncio.run(evals.run(args.scenarios, Settings(), runbooks))
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            for r in results:
                calls = "\n".join(
                    f"{i}. `{c['name']}` {json.dumps(c['args'])[:300]}"
                    + (" (error)" if c["error"] else "")
                    for i, c in enumerate(r["call_log"], 1)
                )
                result = r.get("answer") or r["report"] or r.get("check")
                body = f"{result}\n\n**Tool calls**\n{calls}\n"
                (args.out / f"{r['scenario']}.md").write_text(body)
        print(json.dumps(results, indent=2) if args.json else evals.table(results))
        return 0 if all(r["passed"] for r in results) else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
