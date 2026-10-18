"""Record the Grafana Scenarios from the kind demo's LGTM stack (`make lgtm`).

    kubectl --context kind-aiops -n observability port-forward svc/lgtm 13000:3000 &
    uv run python evals/record_grafana.py /path/to/mcp-grafana [http://localhost:13000]

The binary must be the version the Dockerfile pins, built for this machine; it
runs with the registry's own flags. Every call goes through the Hub's real path
(build_mcp: proxy, env allowlist, grafana_* names), so the recording lines up with
replay. Each tool keeps one result, matched on its datasource only: free-form
LogQL, TraceQL and time ranges still find it, a wrong datasource doesn't.
"""

import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml
from fastmcp import Client

from aiops_agent import agent, contracts
from aiops_agent.config import Settings
from aiops_agent.servers import vendors

OUT = Path(__file__).parent / "scenarios"
PINNED = re.search(
    r"MCP_GRAFANA_VERSION=(\S+)", (Path(__file__).parent.parent / "Dockerfile").read_text()
)

LOGS = {
    "list_datasources": "read",
    "list_loki_label_names": "read",
    "list_loki_label_values": "read",
    "query_loki_stats": "read",
    "query_loki_patterns": "read",
    "query_loki_logs": "read",
    "generate_deeplink": "read",
}
TRACES = {
    **LOGS,
    "search_tempo_traces": "read",
    "get_tempo_trace": "read",
    "list_tempo_attribute_values": "read",
}


def alert(name: str, service: str, summary: str) -> dict[str, Any]:
    labels = {"alertname": name, "service_name": service, "severity": "warning"}
    return {
        "status": "firing",
        "commonLabels": {"alertname": name, "service_name": service},
        "alerts": [{"status": "firing", "labels": labels, "annotations": {"summary": summary}}],
    }


def result(r: Any) -> Any:
    """What replay serves: the tool's structured content, as FastMCP gives it."""
    if r.is_error:
        return {"error": r.content[0].text}
    data = r.structured_content
    if isinstance(data, dict) and set(data) == {"result"}:
        return data["result"]
    if data is not None:
        return data
    text = r.content[0].text
    try:
        return json.loads(text)
    except ValueError:
        return text


def check_version(binary: str) -> None:
    run = subprocess.run([binary, "-version"], capture_output=True, text=True)  # noqa: S603
    assert PINNED and run.stdout.strip() == PINNED[1], f"{binary}: {run.stdout}, pinned {PINNED}"


async def record(binary: str, url: str) -> None:
    vendors.VENDORS["grafana"] = vendors.Spec(
        (binary, *vendors.VENDORS["grafana"].command[1:]),
        vendors.VENDORS["grafana"].env,
        vendors.VENDORS["grafana"].guide,
    )
    grafana = {"name": "grafana", "vendor": "grafana", "env": {"GRAFANA_URL": url}, "tools": TRACES}
    c = contracts.build({"id": "record", "name": "Record", "integrations": [grafana]})
    toolbox = agent.build_mcp(c, Settings())

    async with Client(toolbox.mcp) as client:

        async def call(
            tools: dict[str, list[Any]], tool: str, keys: tuple[str, ...] = (), **args: Any
        ) -> Any:
            got = result(await client.call_tool(f"grafana_{tool}", args, raise_on_error=False))
            match = {k: v for k, v in args.items() if k in ("datasourceUid", *keys)}
            tools.setdefault(f"grafana_{tool}", []).append({"match": match, "result": got})
            return got

        async def common(tools: dict[str, list[Any]], service: str) -> tuple[str, str]:
            sources = await call(tools, "list_datasources")
            uid = {d["type"]: d["uid"] for d in sources["datasources"]}
            loki = uid["loki"]
            await call(tools, "list_loki_label_names", datasourceUid=loki)
            await call(
                tools, "list_loki_label_values", datasourceUid=loki, labelName="service_name"
            )
            selector = f'{{service_name="{service}"}}'
            await call(tools, "query_loki_stats", datasourceUid=loki, logql=selector)
            await call(tools, "query_loki_patterns", datasourceUid=loki, logql=selector)
            await call(tools, "query_loki_logs", datasourceUid=loki, logql=selector, limit=50)
            await deeplink(tools, loki, {"refId": "A", "expr": selector})
            return loki, uid["tempo"]

        async def deeplink(tools: dict[str, list[Any]], uid: str, query: dict[str, str]) -> None:
            """One explore link per datasource: replay serves it for any query there."""
            args = {"datasourceUid": uid, "queries": [query], "timeRange": {"from": "now-1h"}}
            await call(tools, "generate_deeplink", resourceType="explore", **args)

        logs: dict[str, list[Any]] = {}
        await common(logs, "payments")

        traces: dict[str, list[Any]] = {}
        _, tempo = await common(traces, "storefront")
        query = '{resource.service.name="storefront" && duration > 2s}'
        found = await call(traces, "search_tempo_traces", datasourceUid=tempo, query=query)
        await call(
            traces, "list_tempo_attribute_values", datasourceUid=tempo, name="resource.service.name"
        )
        await deeplink(traces, tempo, {"refId": "A", "queryType": "traceql", "query": query})
        for t in found["traces"][:5]:
            await call(
                traces, "get_tempo_trace", ("trace_id",), datasourceUid=tempo, trace_id=t["traceID"]
            )

    write(
        "grafana-log-patterns",
        "A Contract with Grafana only: payments charges fail, and only the logs say why, "
        "among noisier lines. Recorded from the kind demo's LGTM stack (make lgtm).",
        alert(
            "PaymentsHighErrorRate",
            "payments",
            "8% of POST /charge requests return 5xx over the last 10 minutes.",
        ),
        {
            "category": ["dependency_failure"],
            "keywords": ["fraud-check"],
            "links": 1,
            "max_tool_calls": 12,
        },
        LOGS,
        logs,
    )
    write(
        "grafana-slow-traces",
        "A Contract with Grafana only: product pages are slow, the logs say only that, and "
        "the traces show which span takes the time. Recorded from the kind demo (make lgtm).",
        alert(
            "StorefrontHighLatency",
            "storefront",
            "p99 latency of GET /product/{sku} is above 2s.",
        ),
        {
            "category": ["dependency_failure", "app_error", "capacity"],
            "keywords": ["inventory"],
            "links": 1,
            "max_tool_calls": 12,
        },
        TRACES,
        traces,
    )


def write(
    name: str,
    description: str,
    alert: dict[str, Any],
    expect: dict[str, Any],
    allowed: dict[str, str],
    tools: dict[str, list[Any]],
) -> None:
    body = {
        "description": description,
        "clusters": {},
        "integrations": [{"name": "grafana", "vendor": "grafana", "tools": allowed}],
        "alert": alert,
        "expect": expect,
        "tools": tools,
    }
    path = OUT / f"{name}.yaml"
    path.write_text(yaml.safe_dump(body, sort_keys=False, width=100, allow_unicode=True))
    print(f"wrote {path} ({path.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    check_version(sys.argv[1])
    asyncio.run(record(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "http://localhost:13000"))
