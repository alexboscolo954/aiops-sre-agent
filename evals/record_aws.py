"""Record the AWS Scenario from a sandbox account, inside the Hub image.

A Lambda function, checkout, did a 1.2 s inventory lookup with a 10 s timeout until
its timeout was cut to 1 s; then every call timed out and its Errors alarm fired.
Run it in the image, through the Hub's real path, with the read-only IAM user's key:

    AWS_KEY="$(cat key.json)" AIOPS_SCRUB='{"real": "fake", ...}' docker run --rm \\
      -e AWS_KEY -e AIOPS_SCRUB -v "$PWD/evals:/evals" \\
      --entrypoint /app/.venv/bin/python aiops-sre-agent:ci /evals/record_aws.py <account> <region>

key.json is `aws iam create-access-key` output. This repo is public: the account id
maps to a fixed fake, the region to us-east-1 (what a replayed aws Contract names),
and AIOPS_SCRUB adds the rest (the deployer's user name); every access key id becomes
AWS's example one. Nothing is written if a real value survives. Each tool keeps one
result, whatever its arguments, except get_metric_data, matched on the metric.
query_logs' one result is two real queries merged, newest first: the newest failures
and the last healthy lines.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml
from fastmcp import Client
from pydantic import SecretStr
from scrub import mask_aws_key_ids, refuse_leaks, scrubber  # evals/scrub.py, next to this file

from aiops_agent import agent, contracts
from aiops_agent.config import Settings

OUT = Path(__file__).parent / "scenarios"
ACCOUNT, REGION = "123456789012", "us-east-1"
FUNCTION, GROUP = "checkout", "/aws/lambda/checkout"


def result(r: Any) -> Any:
    """What replay serves: the tool's structured content, as FastMCP gives it."""
    if r.is_error:
        return {"error": r.content[0].text}
    data = r.structured_content
    if isinstance(data, dict) and set(data) == {"result"}:
        return data["result"]
    return data if data is not None else json.loads(r.content[0].text)


async def record(account: str, region: str) -> None:
    fakes = {account: ACCOUNT, region: REGION, **json.loads(os.environ.get("AIOPS_SCRUB", "{}"))}
    scrub = scrubber(fakes, set())
    key = json.loads(os.environ["AWS_KEY"])["AccessKey"]
    aws = {
        "name": "aws",
        "regions": [region],
        "access_key_id": key["AccessKeyId"],
        "secret_access_key_secret": "aws-key",
    }
    secret = {"aws-key": SecretStr(key["SecretAccessKey"])}
    c = contracts.build({"id": "record", "name": "Record", "integrations": [aws]}, secrets=secret)
    toolbox = agent.build_mcp(c, Settings())
    tools: dict[str, list[Any]] = {}

    async with Client(toolbox.mcp) as client:

        async def call(tool: str, **args: Any) -> Any:
            got = result(await client.call_tool(f"aws_{tool}", args, raise_on_error=False))
            print(f"{tool}: {str(scrub(got))[:150]}", file=sys.stderr)
            return got

        def keep(tool: str, got: Any, match: dict[str, Any] | None = None) -> None:
            tools.setdefault(f"aws_{tool}", []).append({"match": match or {}, "result": scrub(got)})

        keep("describe_alarms", await call("describe_alarms"))
        dims = {"FunctionName": FUNCTION}
        keep("list_metrics", await call("list_metrics", namespace="AWS/Lambda", dimensions=dims))
        for metric, stat in (("Errors", "Sum"), ("Invocations", "Sum"), ("Duration", "Maximum")):
            got = await call(
                "get_metric_data",
                namespace="AWS/Lambda",
                metric_name=metric,
                dimensions=dims,
                stat=stat,
                period=60,
                minutes=30,
            )
            keep("get_metric_data", got, {"metric_name": metric})
        keep("describe_log_groups", await call("describe_log_groups", prefix="/aws/lambda/"))
        newest = "fields @timestamp, @message | sort @timestamp desc | limit 20"
        healthy = (
            "fields @timestamp, @message | filter @message like /inventory lookup took/ "
            "| sort @timestamp desc | limit 5"
        )
        rows = []
        for q in (newest, healthy):
            rows += (await call("query_logs", log_groups=[GROUP], query=q, minutes=30))["rows"]
        rows.sort(key=lambda r: r.get("@timestamp", ""), reverse=True)
        keep("query_logs", {"status": "Complete", "rows": rows})
        events = await call("lookup_events", minutes=60, resource_name=FUNCTION)
        # Lambda assuming its own role on each cold start: noise, and it names session keys.
        keep("lookup_events", [e for e in events if e["event"] != "AssumeRole"])

    body = {
        "description": "A Contract with AWS only: the checkout Lambda function worked until "
        "its timeout was cut from 10 s to 1 s, below its 1.2 s inventory lookup; then every "
        "call timed out. Recorded from a sandbox account (evals/record_aws.py).",
        "clusters": {},
        "integrations": ["aws"],
        "alert": alert(),
        "expect": {
            "category": ["bad_config", "bad_rollout"],
            "keywords": ["timeout", "1.2"],
            "max_tool_calls": 12,
        },
        "tools": tools,
    }
    text = yaml.safe_dump(body, sort_keys=False, width=100, allow_unicode=True)
    text = mask_aws_key_ids(text)
    refuse_leaks(text, fakes)
    path = OUT / "aws-lambda-timeout-cut.yaml"
    path.write_text(text)
    print(f"wrote {path} ({path.stat().st_size // 1024} KiB)", file=sys.stderr)


def alert() -> dict[str, Any]:
    labels = {"alertname": "checkout-errors", "function_name": FUNCTION, "severity": "critical"}
    summary = "Lambda function checkout reports errors (CloudWatch alarm checkout-errors)."
    return {
        "status": "firing",
        "commonLabels": {"alertname": "checkout-errors", "function_name": FUNCTION},
        "alerts": [{"status": "firing", "labels": labels, "annotations": {"summary": summary}}],
    }


if __name__ == "__main__":
    asyncio.run(record(sys.argv[1], sys.argv[2]))
