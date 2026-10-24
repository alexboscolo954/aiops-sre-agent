"""Command line: `aiops triage`, `aiops serve`, `aiops mcp`, `aiops eval`, `aiops contracts`,
`aiops integrations`, `aiops incidents`, `aiops sizing`."""

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx

from aiops_agent import agent, contracts, embeddings, evals, masking, sizing, usage
from aiops_agent.config import Settings, refuse_moved
from aiops_agent.models import AlertGroup
from aiops_agent.servers import vendors
from aiops_agent.slack import Slack
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
    async with agent.open_agent(settings, toolbox, model, masker=masking.for_contract(c)) as a:
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


def collect_usage(c: contracts.Contract, windows: list[int]) -> tuple[usage.Collected, int]:
    """usage.collect, with missing metrics, Workload-less pods and failed clusters on
    stderr, and an exit status."""
    found = usage.collect(c, windows)
    if not found.clusters:
        print(f"{c.id}: no cluster has a Prometheus (prometheus integration or prometheus_url)")
        return found, 1
    for cluster, error in found.clusters.items():
        if error:
            print(f"{c.id}/{cluster}: {error}", file=sys.stderr)
    for note in found.notes:
        print(note, file=sys.stderr)
    return found, 1 if any(found.clusters.values()) else 0


def _name(cluster: str, r: usage.ContainerUsage) -> str:
    w = r.workload
    return f"{cluster}/{w.namespace}/{w.kind}/{w.name}/{r.container}"


def sizing_usage(contract_id: str, window: str, as_json: bool) -> int:
    """Every Workload container's usage over the window, per cluster, read-only: what
    Sizings are computed from (slice 9.1). Missing metrics are named, never guessed."""
    seconds = window_seconds(window)
    collected, status = collect_usage(contract(Settings(), contract_id), [seconds])
    found = collected.by_window[seconds]
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
    collected, status = collect_usage(c, c.sizing.windows())
    out = sizing.rows(c, collected.by_window, time.time())
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
        texts = [r["text"] for r in row["risks"] if r["kind"] not in sizing.DERIVED]
        risks = f" | risk: {'; '.join(texts)}" if texts else ""
        print(f"{head}: {', '.join(parts)}{short}{risks}")
    return status


def _store_url(settings: Settings) -> str:
    if not settings.database_url:
        raise SystemExit("set AIOPS_DATABASE_URL")
    return settings.database_url.get_secret_value()


async def sizing_refresh(contract_id: str) -> int:
    """Store a Sizing run for the Contract now, as the Hub does hourly (slice 9.4)."""
    import time

    settings = Settings()
    c = contract(settings, contract_id)
    async with connect(_store_url(settings)) as pool:
        store = Store(pool)
        await store.migrate()
        found = await sizing.store_run(store, c, time.time(), every=0)
    if found is None:
        print(f"{c.id}: no cluster has a Prometheus (prometheus integration or prometheus_url)")
        return 1
    for note in found.notes:
        print(note, file=sys.stderr)
    for cluster, error in sorted(found.clusters.items()):
        print(f"{c.id}/{cluster}: {error or 'stored'}")
    return 1 if any(found.clusters.values()) else 0


_utc = sizing.utc


def _signed(change: dict[str, Any], key: str, currency: str | None) -> str:
    """A change in a group's requests or waste: money when priced, else cores and GiB."""
    if currency:
        return f"{change['cost'][key]:+,.2f} {currency}/month"
    q = change[key]
    return f"{q['cpu']:+.2f} cores, {q['memory'] / sizing.GIB:+.2f} GiB"


async def sizing_cost(contract_id: str, by: str, back: str | None, as_json: bool) -> int:
    """What the Contract's requests and waste cost, grouped (slice 10.2), from each
    cluster's latest stored run; with --compare, the change since then (10.3a)."""
    import time

    settings = Settings()
    c = contract(settings, contract_id)
    if by not in sizing.groupings(c):
        print(f"--by: {c.id} groups by {', '.join(sizing.groupings(c))}", file=sys.stderr)
        return 2
    try:
        seconds = None if back is None else contracts.duration_s(back)
    except ValueError as e:
        print(f"--compare: {e}", file=sys.stderr)
        return 2
    async with connect(_store_url(settings)) as pool:
        store = Store(pool)
        await store.migrate()
        out = await sizing.cost(store, c, by, time.time(), seconds)
    if as_json:
        print(json.dumps(out, indent=2))
        return 0
    if not out.pop("clusters"):
        print(f"{c.id}: no Sizings stored yet (`aiops sizing refresh`)")
        return 1
    currency, cmp = out["currency"], out.get("compare")

    def line(g: dict[str, Any]) -> str:
        if currency:
            asked = sizing.money(g["cost"]["requests"], currency)
            saved = sizing.money(g["cost"]["waste"], currency)
        else:
            asked, saved = sizing.quantities(g["requests"]), sizing.quantities(g["waste"])
        if cmp:
            asked += f" ({_signed(g['change'], 'requests', currency)})"
            saved += f" ({_signed(g['change'], 'waste', currency)})"
        return f"requests {asked}, savings available {saved}"

    print(f"{c.id} by {by}: requests in its namespaces, not the nodes")
    for g in out["groups"]:
        print(f"{g['group']}: {line(g)}, {g['workloads']} Workloads")
    print(f"total: {line({**out['total'], 'change': cmp and cmp['change']})}")
    if cmp:
        for cluster, at in cmp["clusters"].items():
            if at["at"] is None:
                print(f"{cluster}: no run that old, oldest {_utc(at['oldest'])}; left out")
            else:
                print(f"{cluster}: compared with its run of {_utc(at['at'])}")
        if cmp["left_out"]:
            print(
                f"left out, requests or labels unknown then: {', '.join(cmp['left_out'])}",
                file=sys.stderr,
            )
    for w in out["warnings"]:
        print(f"warning: {w}", file=sys.stderr)
    return 0


async def sizing_waste(contract_id: str, as_json: bool) -> int:
    """The Contract's Workloads ranked by waste (requests above their Sizings), with
    their risks, from each cluster's latest stored run (slice 9.4)."""
    settings = Settings()
    c = contract(settings, contract_id)
    async with connect(_store_url(settings)) as pool:
        store = Store(pool)
        await store.migrate()
        rows, clusters = await store.latest_sizings(c.id, {t.cluster for t in usage.targets(c)})
    out = {"contract": c.id, **sizing.report(rows, clusters, c)}
    ranked, total, currency = out["workloads"], out["total"], out.get("currency")
    if as_json:
        print(json.dumps(out, indent=2))
        return 0
    if not clusters:
        print(
            f"{c.id}: no Sizings stored yet (the Hub stores them hourly; or `aiops sizing refresh`)"
        )
        return 1
    for cluster, st in sorted(clusters.items()):
        line = f"{cluster}: Sizings as of {_utc(st['at'])}"
        if st["error"]:
            line += f"; stale since {_utc(st['since'])}: {st['error']}"
        print(line)
    if currency:
        cost = out["cost"]
        print(
            f"{c.id}: waste {sizing.money(cost['waste'], currency)} "
            f"({sizing.quantities(total)}); "
            f"requests cost {sizing.money(cost['requests'], currency)}"
        )
    else:
        print(f"{c.id}: waste {sizing.quantities(total)}")
    quiet = 0
    for w in ranked:
        kinds = sorted({r["kind"] for r in w["risks"]})
        if not kinds and sizing.rank(w) == 0:
            quiet += 1
            continue
        risk = f" | risk: {', '.join(kinds)}" if kinds else ""
        cost = (
            f"{sizing.money(w['cost']['waste'], currency)} of "
            f"{sizing.money(w['cost']['requests'], currency)}, "
            if currency
            else ""
        )
        print(
            f"{w['workload']}: {cost}{sizing.quantities(w['waste'])}, avg {w['pods']:g} pods{risk}"
        )
    if quiet:
        print(f"{quiet} more Workloads: no waste, no risk")
    if out["learning"]:
        learning = [
            f"{r['workload']} ({r['history_h']:g} h of {r['needs_h']:g} h)" for r in out["learning"]
        ]
        print(f"learning: {', '.join(learning)}")
    if out["excluded"]:
        print(f"excluded: {', '.join(r['workload'] for r in out['excluded'])}")
    return 0


async def sizing_digest(contract_id: str, post: bool) -> int:
    """The weekly Sizing digest (slice 9.5b) now; with post, also to the operator
    channel. The Hub's schedule is left as it is."""
    import time

    settings = Settings()
    c = contract(settings, contract_id)
    if post and not (c.slack and settings.slack_bot_token):
        raise SystemExit("--post needs AIOPS_SLACK_BOT_TOKEN and the Contract's slack:")
    async with connect(_store_url(settings)) as pool:
        store = Store(pool)
        await store.migrate()
        text = await sizing.digest(store, c, time.time(), settings.console_url)
    print(text)
    if post:
        assert c.slack is not None
        async with httpx.AsyncClient() as http:
            ts = await Slack(settings.slack_bot_token, http).post(c.slack.operator_channel, text)
        print(f"posted: {ts}" if ts else "not posted (see the log)", file=sys.stderr)
        return 0 if ts else 1
    return 0


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
    zr = zsub.add_parser("refresh", help="store a Sizing run now, as the Hub does hourly")
    zr.add_argument("--contract", required=True, help="a Contract id in AIOPS_CONTRACTS_DIR")
    zw = zsub.add_parser("waste", help="Workloads ranked by waste, with risks, as stored")
    zw.add_argument("--contract", required=True, help="a Contract id in AIOPS_CONTRACTS_DIR")
    zw.add_argument("--json", action="store_true")
    zc = zsub.add_parser("cost", help="requests and waste grouped, by what they cost")
    zc.add_argument("--contract", required=True, help="a Contract id in AIOPS_CONTRACTS_DIR")
    zc.add_argument("--by", default="namespace", help="namespace, team or label:<key>")
    zc.add_argument("--compare", metavar="AGO", help="the change since then: 1d, 7d, 30d")
    zc.add_argument("--json", action="store_true")
    zd = zsub.add_parser("digest", help="the weekly Sizing digest, now")
    zd.add_argument("--contract", required=True, help="a Contract id in AIOPS_CONTRACTS_DIR")
    zd.add_argument("--post", action="store_true", help="also post it to the operator channel")

    args = parser.parse_args(argv)
    if args.cmd == "sizing":
        if args.sizing_cmd == "show":
            return sizing_show(args.contract, args.json)
        if args.sizing_cmd == "refresh":
            return asyncio.run(sizing_refresh(args.contract))
        if args.sizing_cmd == "waste":
            return asyncio.run(sizing_waste(args.contract, args.json))
        if args.sizing_cmd == "cost":
            return asyncio.run(sizing_cost(args.contract, args.by, args.compare, args.json))
        if args.sizing_cmd == "digest":
            return asyncio.run(sizing_digest(args.contract, args.post))
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
