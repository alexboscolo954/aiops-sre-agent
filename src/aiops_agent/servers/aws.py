"""AWS MCP server: the Contract's account, read-only (slice 5.2). A builtin, not AWS's
official servers: the local CloudWatch one claims nothing read-only (every call would
need approval) and adds 249 MB; the remote one reads data only through `run_script`,
which claims destructive.

CloudWatch metrics and alarms, Logs Insights and CloudTrail's management events, with
the Contract's IAM user key, signed here (SigV4): the key never leaves the Hub. Every
call goes to one of the Contract's regions; the IAM user's read-only policies are the
hard limit (CloudWatchReadOnlyAccess, AWSCloudTrail_ReadOnlyAccess).
"""

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import SecretStr

from aiops_agent.servers import Access

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
TOOLS = (
    "describe_alarms",
    "list_metrics",
    "get_metric_data",
    "describe_log_groups",
    "query_logs",
    "lookup_events",
)
ACCESS: dict[str, Access] = dict.fromkeys(TOOLS, "read")  # ADR 0002
# Service: (endpoint prefix, JSON protocol version, X-Amz-Target prefix).
SERVICES = {
    "monitoring": ("monitoring", "1.0", "GraniteServiceVersion20100801"),
    "logs": ("logs", "1.1", "Logs_20140328"),
    "cloudtrail": ("cloudtrail", "1.1", "CloudTrail_20131101"),
}
QUERY_SECONDS = 20  # a Logs Insights query still running then is stopped
EVENT_LIMIT = 2000  # chars of one CloudTrail event's request and response
GUIDE = """\
AWS ({name}_ tools), regions {regions} (the first is the default): what's alarming
({name}_describe_alarms, state ALARM) names the metric and its dimensions; read it
({name}_get_metric_data; {name}_list_metrics finds names and dimensions). Logs:
{name}_describe_log_groups, then {name}_query_logs with Logs Insights, such as
fields @timestamp, @message | filter @message like /ERROR/ | sort @timestamp desc |
limit 20. What changed: {name}_lookup_events around the onset (deploys, config
updates, by resource name or event name).
"""


def _hmac(key: bytes, text: str) -> bytes:
    return hmac.new(key, text.encode(), hashlib.sha256).digest()


def authorization(
    method: str,
    host: str,
    path: str,
    query: str,
    headers: dict[str, str],
    body: bytes,
    region: str,
    service: str,
    key_id: str,
    secret: str,
    amz_date: str,
) -> str:
    """The SigV4 Authorization header for a request whose headers (host and
    x-amz-date among them) are all signed."""
    signed = sorted(k.lower() for k in headers)
    lower = {k.lower(): " ".join(v.split()) for k, v in headers.items()}
    canonical = "\n".join(
        [
            method,
            path,
            query,
            *(f"{k}:{lower[k]}" for k in signed),
            "",
            ";".join(signed),
            hashlib.sha256(body).hexdigest(),
        ]
    )
    scope = f"{amz_date[:8]}/{region}/{service}/aws4_request"
    to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()]
    )
    key = _hmac(f"AWS4{secret}".encode(), amz_date[:8])
    for part in (region, service, "aws4_request"):
        key = _hmac(key, part)
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return (
        f"AWS4-HMAC-SHA256 Credential={key_id}/{scope}, "
        f"SignedHeaders={';'.join(signed)}, Signature={signature}"
    )


def _iso(t: Any) -> Any:
    """AWS JSON timestamps are epoch seconds."""
    return datetime.fromtimestamp(t, UTC).strftime("%FT%TZ") if isinstance(t, int | float) else t


def build_server(
    regions: list[str],
    key_id: str,
    secret: SecretStr,
    http: httpx.Client | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FastMCP:
    http = http or httpx.Client(timeout=15)
    mcp = FastMCP("aws", instructions="Read the Contract's AWS account.")

    def where(region: str | None) -> str:
        region = region or regions[0]
        if region not in regions:
            raise ToolError(f"{region!r} isn't one of this Contract's regions: {regions}")
        return region

    def api(service: str, operation: str, body: dict[str, Any], region: str | None) -> Any:
        prefix, version, target = SERVICES[service]
        region = where(region)
        host = f"{prefix}.{region}.amazonaws.com"
        data = json.dumps(body).encode()
        headers = {
            "content-type": f"application/x-amz-json-{version}",
            "host": host,
            "x-amz-date": now().strftime("%Y%m%dT%H%M%SZ"),
            "x-amz-target": f"{target}.{operation}",
        }
        auth = authorization(
            "POST", host, "/", "", headers, data, region, service,
            key_id, secret.get_secret_value(), headers["x-amz-date"],
        )  # fmt: skip
        try:
            resp = http.post(
                f"https://{host}/", content=data, headers={**headers, "authorization": auth}
            )
        except httpx.HTTPError as e:
            raise ToolError(f"AWS {service} unreachable: {type(e).__name__}") from None
        if resp.status_code != 200:  # AWS's error names the problem, never the signature
            try:
                error = resp.json()
            except ValueError:
                error = {}
            kind = str(error.get("__type", "")).rsplit("#", 1)[-1]
            why = error.get("message") or error.get("Message") or resp.reason_phrase
            raise ToolError(f"AWS {service} {operation}: {resp.status_code} {kind}: {why}")
        return resp.json()

    def since(minutes: int) -> tuple[datetime, datetime]:
        end = now()
        return end - timedelta(minutes=max(1, min(minutes, 7 * 24 * 60))), end

    @mcp.tool(annotations=READ)
    def describe_alarms(
        state: str | None = None, prefix: str | None = None, region: str | None = None
    ) -> list[dict[str, Any]]:
        """CloudWatch metric alarms, optionally only those in a state (ALARM, OK,
        INSUFFICIENT_DATA) or whose name starts with `prefix`."""
        body: dict[str, Any] = {"MaxRecords": 50}
        if state:
            body["StateValue"] = state
        if prefix:
            body["AlarmNamePrefix"] = prefix
        data = api("monitoring", "DescribeAlarms", body, region)
        keep = ("AlarmName", "StateValue", "StateReason", "StateUpdatedTimestamp", "Namespace",
                "MetricName", "Dimensions", "Statistic", "Period", "Threshold",
                "ComparisonOperator")  # fmt: skip
        return [{k: a[k] for k in keep if k in a} for a in data.get("MetricAlarms", [])]

    @mcp.tool(annotations=READ)
    def list_metrics(
        namespace: str,
        metric_name: str | None = None,
        dimensions: dict[str, str] | None = None,
        region: str | None = None,
    ) -> list[dict[str, Any]]:
        """Metrics in a namespace (AWS/Lambda, AWS/EC2, ...), with their dimensions."""
        body: dict[str, Any] = {"Namespace": namespace}
        if metric_name:
            body["MetricName"] = metric_name
        if dimensions:
            body["Dimensions"] = [{"Name": k, "Value": v} for k, v in dimensions.items()]
        return list(api("monitoring", "ListMetrics", body, region).get("Metrics", []))[:100]

    @mcp.tool(annotations=READ)
    def get_metric_data(
        namespace: str,
        metric_name: str,
        dimensions: dict[str, str],
        stat: str = "Sum",
        period: int = 300,
        minutes: int = 60,
        region: str | None = None,
    ) -> dict[str, Any]:
        """One metric over the last `minutes`, one point per `period` seconds, oldest
        first. stat: Sum, Average, Maximum, Minimum, SampleCount or p99."""
        start, end = since(minutes)
        metric = {
            "Namespace": namespace,
            "MetricName": metric_name,
            "Dimensions": [{"Name": k, "Value": v} for k, v in dimensions.items()],
        }
        query = {"Id": "m", "MetricStat": {"Metric": metric, "Period": period, "Stat": stat}}
        body = {
            "MetricDataQueries": [query],
            "StartTime": int(start.timestamp()),
            "EndTime": int(end.timestamp()),
            "ScanBy": "TimestampAscending",
        }
        results = api("monitoring", "GetMetricData", body, region).get("MetricDataResults", [])
        r = results[0] if results else {}
        points = zip(r.get("Timestamps", []), r.get("Values", []), strict=False)
        return {
            "metric": f"{namespace} {metric_name} {stat} per {period}s",
            "status": r.get("StatusCode"),
            "points": [[_iso(t), v] for t, v in points],
        }

    @mcp.tool(annotations=READ)
    def describe_log_groups(
        prefix: str | None = None, region: str | None = None
    ) -> list[dict[str, Any]]:
        """CloudWatch log groups, optionally those whose name starts with `prefix`
        (/aws/lambda/checkout, /ecs/...)."""
        body: dict[str, Any] = {"limit": 50}
        if prefix:
            body["logGroupNamePrefix"] = prefix
        groups = api("logs", "DescribeLogGroups", body, region).get("logGroups", [])
        return [{k: g[k] for k in ("logGroupName", "storedBytes") if k in g} for g in groups]

    @mcp.tool(annotations=READ)
    def query_logs(
        log_groups: list[str],
        query: str,
        minutes: int = 60,
        region: str | None = None,
    ) -> dict[str, Any]:
        """Run a Logs Insights query over log groups for the last `minutes` and return
        its rows (at most 100)."""
        if not log_groups:
            raise ToolError("name at least one log group")
        start, end = since(minutes)
        body = {
            "logGroupNames": log_groups[:10],
            "queryString": query,
            "startTime": int(start.timestamp()),
            "endTime": int(end.timestamp()),
            "limit": 100,
        }
        query_id = api("logs", "StartQuery", body, region)["queryId"]
        deadline = time.monotonic() + QUERY_SECONDS
        while True:
            data = api("logs", "GetQueryResults", {"queryId": query_id}, region)
            if data.get("status") not in ("Scheduled", "Running"):
                break
            if time.monotonic() > deadline:
                api("logs", "StopQuery", {"queryId": query_id}, region)
                raise ToolError(f"the query ran past {QUERY_SECONDS}s and was stopped: narrow it")
            time.sleep(1)
        rows = [
            {f["field"]: f["value"] for f in row if not f["field"].startswith("@ptr")}
            for row in data.get("results", [])
        ]
        return {"status": data.get("status"), "rows": rows}

    @mcp.tool(annotations=READ)
    def lookup_events(
        minutes: int = 180,
        resource_name: str | None = None,
        event_name: str | None = None,
        region: str | None = None,
    ) -> list[dict[str, Any]]:
        """CloudTrail management events (deploys, config changes) of the last `minutes`,
        newest first, optionally for one resource name or one event name."""
        start, end = since(minutes)
        body: dict[str, Any] = {
            "StartTime": int(start.timestamp()),
            "EndTime": int(end.timestamp()),
            "MaxResults": 50,
        }
        if resource_name:
            body["LookupAttributes"] = [
                {"AttributeKey": "ResourceName", "AttributeValue": resource_name}
            ]
        elif event_name:
            body["LookupAttributes"] = [{"AttributeKey": "EventName", "AttributeValue": event_name}]
        events = []
        for e in api("cloudtrail", "LookupEvents", body, region).get("Events", []):
            try:
                detail = json.loads(e.get("CloudTrailEvent", "{}"))
            except ValueError:
                detail = {}
            events.append(
                {
                    "time": detail.get("eventTime"),
                    "event": e.get("EventName"),
                    "source": e.get("EventSource"),
                    "user": e.get("Username"),
                    "resources": [r.get("ResourceName") for r in e.get("Resources", [])],
                    "error": detail.get("errorCode"),
                    "request": json.dumps(detail.get("requestParameters"))[:EVENT_LIMIT],
                }
            )
        return events

    return mcp
