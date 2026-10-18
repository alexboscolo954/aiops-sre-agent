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
from dataclasses import dataclass, field
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
    # Set by the registry on every start, snapshots included, over anything else:
    # telemetry off, which credential to use. A Contract can't set or override them.
    fixed_env: dict[str, str] = field(default_factory=dict)
    # Allowed variables that hold credentials: only from secrets.sops.yaml (env_secrets).
    secret_env: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not Path(self.command[0]).is_absolute():
            raise ValueError(f"vendor command must be an absolute path: {self.command[0]!r}")
        if overlap := sorted(self.env & set(self.fixed_env)):
            raise ValueError(f"the registry fixes these, a Contract can't set them: {overlap}")


AZURE_TOOLS = (
    "advisor_metadata_get",
    "advisor_metadata_list",
    "advisor_recommendation_list",
    "advisor_recommendation_summary",
    "advisor_remediation_get",
    "aks_cluster_get",
    "aks_nodepool_get",
    "applicationinsights_recommendation_list",
    "appservice_webapp_deployment_get",
    "appservice_webapp_diagnostic_diagnose",
    "appservice_webapp_diagnostic_list",
    "appservice_webapp_get",
    "compute_disk_get",
    "compute_vm_get",
    "compute_vmss_get",
    "containerapps_list",
    "cosmos_list",
    "eventhubs_eventhub_consumergroup_get",
    "eventhubs_eventhub_get",
    "eventhubs_namespace_get",
    "functionapp_get",
    "group_list",
    "group_resource_list",
    "monitor_activitylog_list",
    "monitor_healthmodels_get",
    "monitor_healthmodels_list",
    "monitor_metrics_batchquery",
    "monitor_metrics_definitions",
    "monitor_metrics_query",
    "monitor_resource_log_query",
    "monitor_table_list",
    "monitor_table_type_list",
    "monitor_webtests_get",
    "monitor_workspace_list",
    "monitor_workspace_log_query",
    "monitor_workspace_log_search",
    "mysql_list",
    "mysql_server_config_get",
    "mysql_server_param_get",
    "mysql_table_schema_get",
    "postgres_list",
    "postgres_server_config_get",
    "postgres_server_param_get",
    "postgres_table_schema_get",
    "quota_region_availability_list",
    "quota_usage_check",
    "redis_list",
    "resourcehealth_availability-status_get",
    "resourcehealth_health-events_list",
    "servicebus_queue_details",
    "servicebus_topic_details",
    "servicebus_topic_subscription_details",
    "sql_db_get",
    "sql_elastic-pool_list",
    "sql_server_entra-admin_list",
    "sql_server_firewall-rule_list",
    "sql_server_get",
    "storage_account_get",
    "storage_blob_container_get",
    "storage_blob_get",
    "storage_table_list",
    "subscription_list",
)

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
    # Read-only by flag, and only these tools: metadata, health, metrics and logs an SRE
    # reads. Not keyvault (secrets), extension (builds az CLI commands), deploy or
    # terraform; not app settings (often connection strings) nor Cosmos documents
    # (client data). The Contract's `tools` narrows it further.
    "azure": Spec(
        (
            "/opt/azmcp/azmcp",
            "server",
            "start",
            "--read-only",
            "--disable-proxy-tools",
            *(f"--tool={t}" for t in AZURE_TOOLS),
        ),
        frozenset(
            {"AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "AZURE_SUBSCRIPTION_ID"}
        ),
        fixed_env={
            "AZURE_MCP_COLLECT_TELEMETRY": "false",
            # Only the Contract's service principal: never the host's az login,
            # VS Code session or managed identity.
            "AZURE_TOKEN_CREDENTIALS": "EnvironmentCredential",
            "HOME": "/nonexistent",  # no ~/.azure: no default subscription from the host
            # Writable on the read-only root: the container's own tmpfs, uid 10001 only.
            "DOTNET_BUNDLE_EXTRACT_BASE_DIR": "/tmp/azmcp",  # noqa: S108
            "DOTNET_SYSTEM_GLOBALIZATION_INVARIANT": "1",  # slim image: no ICU
        },
        secret_env=frozenset({"AZURE_CLIENT_SECRET"}),
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
    env = {**env, **spec.fixed_env}  # the registry's last: nothing overrides it
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
