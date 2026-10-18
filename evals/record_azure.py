"""Record the Azure Scenario from a sandbox subscription, inside the Hub image.

A Linux App Service web app that worked until its startup command was changed to
`node missing.js`, then served 5xx under traffic. Run it in the image, where the
pinned azmcp is, with the Contract's service principal only:

    AZURE_CLIENT_SECRET=... AIOPS_SCRUB='{"real": "fake", ...}' docker run --rm \\
      -e AZURE_TENANT_ID -e AZURE_CLIENT_ID -e AZURE_SUBSCRIPTION_ID \\
      -e AZURE_CLIENT_SECRET -e AIOPS_SCRUB -v "$PWD/evals:/evals" \\
      --entrypoint /app/.venv/bin/python aiops-sre-agent:ci /evals/record_azure.py <rg> <app>

This repo is public: every result is scrubbed before it is written. The ids, the
resource group and app names map to fixed fakes, AIOPS_SCRUB adds the rest (the
caller's email, object id, tenant domain, IP), and `claims` and `httpRequest`
(who called, from where) are dropped. Nothing is written if a real value survives.
Each tool keeps one result, matched on the resource's name only.
"""

import asyncio
import json
import os
import re
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
SUBSCRIPTION, TENANT, CLIENT = (f"00000000-0000-0000-0000-00000000a00{i}" for i in (1, 2, 3))
RG, APP = "shop-prod-rg", "shop-web"
DROPPED = {"claims", "httpRequest"}

TOOLS = {
    "group_resource_list": "read",
    "appservice_webapp_get": "read",
    "monitor_activitylog_list": "read",
    "monitor_metrics_definitions": "read",
    "monitor_metrics_query": "read",
    "resourcehealth_availability-status_get": "read",
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


def fakes_and_scrub(rg: str, app: str) -> tuple[dict[str, str], Any]:
    fakes = {
        os.environ["AZURE_SUBSCRIPTION_ID"]: SUBSCRIPTION,
        os.environ["AZURE_TENANT_ID"]: TENANT,
        os.environ["AZURE_CLIENT_ID"]: CLIENT,
        rg: RG,
        app: APP,
        **json.loads(os.environ.get("AIOPS_SCRUB", "{}")),
    }
    return fakes, scrubber(fakes, DROPPED)


async def record(rg: str, app: str) -> None:
    fakes, scrub = fakes_and_scrub(rg, app)
    azure = {
        "name": "azure",
        "vendor": "azure",
        "env": {
            v: os.environ[v]
            for v in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_SUBSCRIPTION_ID")
        },
        "env_secrets": {"AZURE_CLIENT_SECRET": "azure-client-secret"},
        "tools": TOOLS,
    }
    secret = {"azure-client-secret": SecretStr(os.environ["AZURE_CLIENT_SECRET"])}
    c = contracts.build({"id": "record", "name": "Record", "integrations": [azure]}, secrets=secret)
    toolbox = agent.build_mcp(c, Settings())
    tools: dict[str, list[Any]] = {}

    async with Client(toolbox.mcp) as client:

        async def call(tool: str, keys: tuple[str, ...] = (), **args: Any) -> Any:
            got = result(await client.call_tool(f"azure_{tool}", args, raise_on_error=False))
            print(f"{tool}: {str(scrub(got))[:150]}", file=sys.stderr)
            match = {k: scrub(args.get(k)) for k in ("app", "resource", "resource-name", *keys)}
            match = {k: v for k, v in match.items() if v is not None}
            tools.setdefault(f"azure_{tool}", []).append({"match": match, "result": scrub(got)})
            return got

        now = datetime.now(UTC)
        since = now - timedelta(hours=2)  # at PT5M, under the 50-bucket cap
        where = {"resource-group": rg}
        site = {"resource-type": "Microsoft.Web/sites", **where}
        await call("group_resource_list", ("resource-group",), **where)
        web = await call("appservice_webapp_get", app=app, **where)
        await call("monitor_activitylog_list", **{"resource-name": app, "hours": 3, "top": 20})
        await call("monitor_metrics_definitions", resource=app, **site)
        await call(
            "monitor_metrics_query",
            resource=app,
            **site,
            **{
                "metric-namespace": "Microsoft.Web/sites",
                "metric-names": "Requests,Http2xx,Http5xx",
            },
            interval="PT5M",
            **{"start-time": f"{since:%FT%TZ}", "end-time": f"{now:%FT%TZ}"},
        )
        resource_id = re.search(r"/subscriptions/[^\"']+/sites/" + re.escape(app), json.dumps(web))
        args = {"resourceId": resource_id[0]} if resource_id else where
        await call("resourcehealth_availability-status_get", **args)

    body = {
        "description": "A Contract with Azure only: a Linux App Service web app worked until "
        "its startup command was changed, then served 5xx. Recorded from a sandbox "
        "subscription (evals/record_azure.py).",
        "clusters": {},
        "integrations": [{"name": "azure", "vendor": "azure", "tools": TOOLS}],
        "alert": alert(),
        "expect": {
            "category": ["bad_config", "bad_rollout"],
            "keywords": ["config", "15:50"],
            "max_tool_calls": 12,
        },
        "tools": tools,
    }
    text = yaml.safe_dump(body, sort_keys=False, width=100, allow_unicode=True)
    refuse_leaks(text, fakes)
    path = OUT / "azure-appservice-bad-startup.yaml"
    path.write_text(text)
    print(f"wrote {path} ({path.stat().st_size // 1024} KiB)", file=sys.stderr)


def alert() -> dict[str, Any]:
    labels = {
        "alertname": "AppServiceHttp5xx",
        "resource_group": RG,
        "app": APP,
        "severity": "critical",
    }
    summary = f"More than half of the requests to App Service {APP} return 5xx."
    return {
        "status": "firing",
        "commonLabels": {"alertname": "AppServiceHttp5xx", "app": APP},
        "alerts": [{"status": "firing", "labels": labels, "annotations": {"summary": summary}}],
    }


if __name__ == "__main__":
    asyncio.run(record(sys.argv[1], sys.argv[2]))
