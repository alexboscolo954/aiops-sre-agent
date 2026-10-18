"""Record the GCP Scenario from a sandbox project, inside the Hub image.

A Cloud Run service, checkout, worked until a new revision set its inventory timeout
(UPSTREAM_TIMEOUT_MS) to 1 ms, then answered 503 under traffic. Run it in the image,
through the Hub's real path, with the Contract's service account key only:

    GOOGLE_SERVICE_ACCOUNT_KEY="$(cat key.json)" AIOPS_SCRUB='{"real": "fake", ...}' \\
    docker run --rm -e GOOGLE_SERVICE_ACCOUNT_KEY -e AIOPS_SCRUB -v "$PWD/evals:/evals" \\
      --entrypoint /app/.venv/bin/python aiops-sre-agent:ci /evals/record_gcp.py <project> <number>

This repo is public: the project id and number map to fixed fakes, AIOPS_SCRUB adds
the rest (the deployer's email), and `requestMetadata` and request IPs and user agents (who called,
from where) are dropped. Nothing is written if a real value survives.
Each tool keeps one result, whatever its filter or query. list_log_entries' one
result is three real calls merged, newest first: the revisions' errors (the newest
ten), their startup lines, and Cloud Run's audit entries (the deploys).
"""

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from fastmcp import Client
from pydantic import SecretStr
from scrub import refuse_leaks, scrubber  # evals/scrub.py, next to this file

from aiops_agent import agent, contracts
from aiops_agent.config import Settings

OUT = Path(__file__).parent / "scenarios"
PROJECT, NUMBER = "shop-prod-4f2a", "100000000001"
DROPPED = {"requestMetadata", "remoteIp", "serverIp", "userAgent"}  # who called, from where
TOOLS = {
    "list_log_names": "read",
    "list_log_entries": "read",
    "list_metric_descriptors": "read",
    "list_timeseries": "read",
    "query_range": "read",
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
    return json.loads(r.content[0].text)


async def record(project: str, number: str) -> None:
    fakes = {project: PROJECT, number: NUMBER, **json.loads(os.environ.get("AIOPS_SCRUB", "{}"))}
    scrub = scrubber(fakes, DROPPED)
    gcp = {
        "name": "gcp",
        "vendor": "gcp",
        "env": {"GOOGLE_CLOUD_PROJECT": project},
        "env_secrets": {"GOOGLE_SERVICE_ACCOUNT_KEY": "gcp-key"},
        "tools": TOOLS,
    }
    key = {"gcp-key": SecretStr(os.environ["GOOGLE_SERVICE_ACCOUNT_KEY"])}
    c = contracts.build({"id": "record", "name": "Record", "integrations": [gcp]}, secrets=key)
    toolbox = agent.build_mcp(c, Settings())
    now = datetime.now(UTC)
    since = (now - timedelta(minutes=40)).strftime("%FT%TZ")
    where = [f"projects/{project}"]
    tools: dict[str, list[Any]] = {}

    async with Client(toolbox.mcp) as client:

        async def call(tool: str, **args: Any) -> Any:
            got = result(await client.call_tool(f"gcp_{tool}", args, raise_on_error=False))
            print(f"{tool}: {str(scrub(got))[:150]}", file=sys.stderr)
            return got

        def keep(tool: str, got: Any) -> None:
            tools[f"gcp_{tool}"] = [{"match": {}, "result": scrub(got)}]

        keep("list_log_names", await call("list_log_names", parent=where[0]))
        run = f'resource.type="cloud_run_revision" AND timestamp>="{since}"'
        logs = {"resourceNames": where, "orderBy": "timestamp desc"}
        errors = await call(
            "list_log_entries", filter=f"{run} AND severity>=ERROR", pageSize=10, **logs
        )
        started = await call(
            "list_log_entries",
            filter=f'{run} AND jsonPayload.message:"listening"',
            pageSize=10,
            **logs,
        )
        audit = await call(
            "list_log_entries",
            filter=f'protoPayload.serviceName="run.googleapis.com" AND timestamp>="{since}"',
            pageSize=10,
            **logs,
        )
        merged = [e for r in (errors, started, audit) for e in r.get("entries", [])]
        merged.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        keep("list_log_entries", {"entries": merged})
        keep(
            "list_metric_descriptors",
            await call(
                "list_metric_descriptors",
                name=where[0],
                filter='metric.type = starts_with("run.googleapis.com/request")',
            ),
        )
        interval = {"startTime": since, "endTime": now.strftime("%FT%TZ")}
        keep(
            "list_timeseries",
            await call(
                "list_timeseries",
                name=where[0],
                filter='metric.type="run.googleapis.com/request_count"',
                interval=interval,
                view="FULL",
                aggregation={
                    "alignmentPeriod": "300s",
                    "perSeriesAligner": "ALIGN_SUM",
                },
            ),
        )
        promql = (
            "sum by (revision_name, response_code_class) "
            '(increase(run_googleapis_com:request_count{monitored_resource="cloud_run_revision"}[5m]))'
        )
        keep(
            "query_range",
            await call(
                "query_range",
                name=where[0],
                location="global",
                query=promql,
                start=interval["startTime"],
                end=interval["endTime"],
                step="300s",
            ),
        )

    body = {
        "description": "A Contract with Google Cloud only: the checkout Cloud Run service "
        "worked until a new revision set its inventory timeout to 1 ms, then answered "
        "503. Recorded from a sandbox project (evals/record_gcp.py).",
        "clusters": {},
        "integrations": [
            {
                "name": "gcp",
                "vendor": "gcp",
                "tools": TOOLS,
                "env": {"GOOGLE_CLOUD_PROJECT": PROJECT},
            }
        ],
        "alert": alert(),
        "expect": {
            "category": ["bad_config", "bad_rollout"],
            "keywords": ["timeout", "00002"],
            "max_tool_calls": 12,
        },
        "tools": tools,
    }
    text = yaml.safe_dump(body, sort_keys=False, width=100, allow_unicode=True)
    refuse_leaks(text, fakes)
    path = OUT / "gcp-cloudrun-bad-timeout.yaml"
    path.write_text(text)
    print(f"wrote {path} ({path.stat().st_size // 1024} KiB)", file=sys.stderr)


def alert() -> dict[str, Any]:
    labels = {"alertname": "CloudRunHigh5xx", "service_name": "checkout", "severity": "critical"}
    summary = "More than half of the requests to Cloud Run service checkout return 5xx."
    return {
        "status": "firing",
        "commonLabels": {"alertname": "CloudRunHigh5xx", "service_name": "checkout"},
        "alerts": [{"status": "firing", "labels": labels, "annotations": {"summary": summary}}],
    }


if __name__ == "__main__":
    asyncio.run(record(sys.argv[1], sys.argv[2]))
