"""Vendor MCP servers the Hub may start, by name: a Contract says `vendor: <name>`.

The command lives here, in the Hub's code, never in the contracts repo: whoever can
push there must not be able to run a program next to every Contract's keys (the
reasoning of ADR 0002 for kubeconfig exec plugins). For the same reason a Contract
may set only the variables its vendor's entry lists: `LD_PRELOAD`, `PATH`,
`NODE_OPTIONS` and the like would run code all the same. Each binary ships in the
image, pinned and checksum-verified like sops (versions in the Dockerfile).

Each vendor's tool schemas are snapshotted into snapshots/<name>.json (slice 4.2):
Scenarios replay against them with no binary, and `aiops integrations snapshot
<name> --check` fails when the pinned server's tools drift from the snapshot.
"""

import difflib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastmcp import Client, FastMCP
from fastmcp.client.transports import StdioTransport
from fastmcp.tools import Tool, ToolResult
from mcp.types import ToolAnnotations


@dataclass(frozen=True)
class Spec:
    command: tuple[str, ...]  # command[0] an absolute path: PATH can't redirect it
    env: frozenset[str]  # the only variables a Contract may set for it
    guide: str = ""  # how to investigate with it, added to the prompt; {name}: the integration
    # Tools whose whole result is a link the Hub may show, built by the vendor from
    # its own base URL, and the guide sentence for each, added when the Contract lists it.
    links: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not Path(self.command[0]).is_absolute():
            raise ValueError(f"vendor command must be an absolute path: {self.command[0]!r}")


VENDORS: dict[str, Spec] = {
    # Read-only by flag (every tool then claims readOnlyHint), no usage reports to
    # Grafana Labs, and no toolset that reaches past its datasources: not `api`
    # (any Grafana endpoint), `rendering`, `docs` (fetches the web), nor the Grafana
    # Cloud-only ones. A Contract's `tools` narrows it further.
    "grafana": Spec(
        (
            "/usr/local/bin/mcp-grafana",
            "--usage-stats=disabled",
            "--disable-write",
            "--enabled-tools=search,datasource,prometheus,loki,tempo,pyroscope,alerting,"
            "dashboard,navigation",
        ),
        frozenset({"GRAFANA_URL", "GRAFANA_SERVICE_ACCOUNT_TOKEN", "GRAFANA_ORG_ID"}),
        """\
Grafana ({name}_ tools): take datasource uids from {name}_list_datasources. For
logs, look at volume and the most frequent line patterns ({name}_query_loki_stats,
{name}_query_loki_patterns) before reading raw lines ({name}_query_loki_logs): a
pattern with a high count often names the failure. For slowness, find slow traces
({name}_search_tempo_traces, TraceQL such as
{{resource.service.name="checkout" && duration > 2s}}) and open one
({name}_get_tempo_trace): the span that takes the time, and its attributes, show
the cause.
""",
        (
            (
                "generate_deeplink",
                "So the Operator can open what you saw, call {name}_generate_deeplink for the\n"
                "key evidence (explore with the datasource uid and your query, or a\n"
                "dashboard) and put the URL it returns, exactly, in that Evidence's link.\n"
                "Only links it returns are shown; a link copied from any other result is\n"
                "dropped.\n",
            ),
        ),
    ),
}
START_SECONDS = 30  # a vendor that never finishes MCP's handshake fails the Run
CALL_SECONDS = 60  # each vendor tool call
SNAPSHOTS = Path(__file__).parent / "snapshots"
# What the model and the approval gate see of a tool; _meta and icons are noise.
SNAPSHOT_FIELDS = ("name", "title", "description", "inputSchema", "outputSchema", "annotations")


def client(spec: Spec, env: dict[str, str]) -> Client[StdioTransport]:
    """The vendor as a subprocess with exactly `env` on top of MCP's safe defaults
    (PATH, HOME, ...). keep_alive off: one process per use, none outlives a Run."""
    transport = StdioTransport(spec.command[0], list(spec.command[1:]), env=env, keep_alive=False)
    return Client(transport, timeout=CALL_SECONDS, init_timeout=START_SECONDS)


async def capture(spec: Spec) -> str:
    """The vendor's tool schemas as stable JSON. Started with no Contract and no
    variables at all, so no credential can end up in a file this public repo commits."""
    async with client(spec, {}) as c:
        tools = await c.list_tools()
    dumped = [t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in tools]
    kept = [{k: t[k] for k in SNAPSHOT_FIELDS if k in t} for t in dumped]
    return json.dumps(sorted(kept, key=lambda t: t["name"]), indent=2, sort_keys=True) + "\n"


async def drift(name: str) -> str:
    """A unified diff from the saved snapshot to the running vendor; empty if none."""
    path = SNAPSHOTS / f"{name}.json"
    saved = path.read_text() if path.exists() else ""
    live = await capture(VENDORS[name])
    diff = difflib.unified_diff(
        saved.splitlines(keepends=True), live.splitlines(keepends=True), str(path), "live"
    )
    return "".join(diff)


class Snapshotted(Tool):
    """A vendor tool rebuilt from its snapshot: same name, schemas and annotations
    as the real one, and no implementation. The replay answers every call first."""

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        raise RuntimeError(f"{self.name} is a snapshot: only a replay can answer it")


def snapshot_server(vendor: str, name: str) -> FastMCP:
    """The vendor's tools from snapshots/<vendor>.json, for replaying a Scenario."""
    path = SNAPSHOTS / f"{vendor}.json"
    if not path.exists():
        raise ValueError(
            f"no schema snapshot for vendor {vendor!r}: run `aiops integrations snapshot {vendor}`"
        )
    server = FastMCP(name)
    for t in json.loads(path.read_text()):
        annotations = t.get("annotations")
        server.add_tool(
            Snapshotted(
                name=t["name"],
                title=t.get("title"),
                description=t.get("description"),
                parameters=t["inputSchema"],
                output_schema=t.get("outputSchema"),
                annotations=ToolAnnotations(**annotations) if annotations else None,
            )
        )
    return server
