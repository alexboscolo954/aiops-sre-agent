"""The AWS builtin (slice 5.2): the Contract's account read-only, signed in the Hub.
Responses are synthetic, in the AWS JSON protocols' documented shapes."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastmcp import Client
from langchain.mcp import MCPAdapter
from pydantic import SecretStr

from aiops_agent import agent, contracts, evals
from aiops_agent.config import Settings
from aiops_agent.servers import aws

KEY_ID, SECRET = "AKIDEXAMPLE", "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
NOW = datetime(2026, 10, 18, 23, 47, 52, tzinfo=UTC)
INTEGRATION = {
    "name": "aws",
    "regions": ["us-east-1", "eu-west-1"],
    "access_key_id": "AKIAIOSFODNN7EXAMPLE",
    "secret_access_key_secret": "aws-key",
}


@pytest.mark.parametrize(
    ("method", "host", "headers", "body", "service", "signature"),
    [
        (  # botocore's SigV4Auth at the same instant gave these signatures
            "GET",
            "example.amazonaws.com",
            {},
            b"",
            "service",
            "e6f19a6f7243f9bcc12d151d74fe0257e5da2a742aed32bd6ed44f7f41cc147b",
        ),
        (
            "POST",
            "monitoring.us-east-1.amazonaws.com",
            {
                "content-type": "application/x-amz-json-1.0",
                "x-amz-target": "GraniteServiceVersion20100801.DescribeAlarms",
            },
            b'{"MaxRecords": 50}',
            "monitoring",
            "eee6ac3dcdaae1d45e4aa0d66818a432f1a2e0e15f2a50a52f8420df660fb856",
        ),
    ],
)
def test_requests_are_signed_as_aws_signs_them(
    method: str, host: str, headers: dict[str, str], body: bytes, service: str, signature: str
) -> None:
    date = "20261018T234752Z"
    signed = {**headers, "host": host, "x-amz-date": date}
    auth = aws.authorization(
        method, host, "/", "", signed, body, "us-east-1", service, KEY_ID, SECRET, date
    )
    assert auth.endswith(f"Signature={signature}")
    assert auth.startswith(f"AWS4-HMAC-SHA256 Credential={KEY_ID}/20261018/us-east-1/{service}/")


def server(answer: Any, seen: list[httpx.Request] | None = None) -> Any:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return answer(request)

    http = httpx.Client(transport=httpx.MockTransport(handle))
    return aws.build_server(
        ["eu-west-1", "us-east-1"], KEY_ID, SecretStr(SECRET), http, lambda: NOW
    )


@pytest.mark.anyio
async def test_every_tool_reads_and_the_hubs_list_matches() -> None:
    async with Client(server(lambda r: httpx.Response(200, json={}))) as c:
        tools = await c.list_tools()
    assert {t.name for t in tools} == set(aws.ACCESS) == set(aws.TOOLS)
    assert all(t.annotations and t.annotations.read_only_hint for t in tools)
    assert set(aws.ACCESS.values()) == {"read"}


@pytest.mark.anyio
async def test_a_call_is_signed_for_the_contracts_region_only() -> None:
    seen: list[httpx.Request] = []
    alarm = {"AlarmName": "checkout-errors", "StateValue": "ALARM", "AlarmArn": "arn:x"}
    async with Client(
        server(lambda r: httpx.Response(200, json={"MetricAlarms": [alarm]}), seen)
    ) as c:
        got = await c.call_tool("describe_alarms", {"state": "ALARM"})
        assert got.structured_content == {
            "result": [{"AlarmName": "checkout-errors", "StateValue": "ALARM"}]
        }
        await c.call_tool("describe_alarms", {"region": "us-east-1"})
        refused = await c.call_tool(
            "describe_alarms", {"region": "ap-south-1"}, raise_on_error=False
        )
    assert refused.is_error and "isn't one of this Contract's regions" in refused.content[0].text
    assert [r.url.host for r in seen] == [
        "monitoring.eu-west-1.amazonaws.com",  # the first region is the default
        "monitoring.us-east-1.amazonaws.com",
    ]
    first = seen[0]
    assert first.headers["x-amz-target"] == "GraniteServiceVersion20100801.DescribeAlarms"
    assert json.loads(first.content) == {"MaxRecords": 50, "StateValue": "ALARM"}
    headers = {k: first.headers[k] for k in ("content-type", "host", "x-amz-date", "x-amz-target")}
    assert first.headers["authorization"] == aws.authorization(
        "POST", first.url.host, "/", "", headers, first.content, "eu-west-1", "monitoring",
        KEY_ID, SECRET, "20261018T234752Z",
    )  # fmt: skip


@pytest.mark.anyio
async def test_an_aws_error_says_why_without_the_signature() -> None:
    denied = {"__type": "com.amazon.coral#AccessDeniedException", "message": "not authorized"}
    async with Client(server(lambda r: httpx.Response(400, json=denied))) as c:
        r = await c.call_tool("describe_log_groups", {}, raise_on_error=False)
    text = r.content[0].text
    assert (
        r.is_error and "logs DescribeLogGroups: 400 AccessDeniedException: not authorized" in text
    )
    assert "Signature" not in text and SECRET not in text


@pytest.mark.anyio
async def test_a_logs_query_waits_for_its_rows_and_is_stopped_when_too_slow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(aws.time, "sleep", lambda s: None)
    statuses = iter(["Running", "Complete"])
    row = [{"field": "@message", "value": "boom"}, {"field": "@ptr", "value": "x"}]

    def answer(request: httpx.Request) -> httpx.Response:
        op = request.headers["x-amz-target"].split(".")[1]
        if op == "StartQuery":
            return httpx.Response(200, json={"queryId": "q1"})
        if op == "GetQueryResults":
            return httpx.Response(200, json={"status": next(statuses, "Running"), "results": [row]})
        return httpx.Response(200, json={"success": True})

    seen: list[httpx.Request] = []
    async with Client(server(answer, seen)) as c:
        args = {"log_groups": ["/aws/lambda/checkout"], "query": "fields @message"}
        got = await c.call_tool("query_logs", args)
        assert got.structured_content == {"status": "Complete", "rows": [{"@message": "boom"}]}
        start = json.loads(seen[0].content)
        assert start["endTime"] - start["startTime"] == 3600
        monkeypatch.setattr(aws, "QUERY_SECONDS", -1)
        slow = await c.call_tool("query_logs", args, raise_on_error=False)
    assert slow.is_error and "was stopped" in slow.content[0].text
    assert seen[-1].headers["x-amz-target"] == "Logs_20140328.StopQuery"


@pytest.mark.anyio
async def test_cloudtrail_events_show_what_changed_capped() -> None:
    detail = {"eventTime": "2026-10-18T22:22:37Z", "requestParameters": {"code": "x" * 5000}}
    event = {
        "EventName": "UpdateFunctionConfiguration20150331v2",
        "EventSource": "lambda.amazonaws.com",
        "Username": "deployer",
        "Resources": [{"ResourceName": "checkout"}],
        "CloudTrailEvent": json.dumps(detail),
    }
    seen: list[httpx.Request] = []
    async with Client(server(lambda r: httpx.Response(200, json={"Events": [event]}), seen)) as c:
        got = await c.call_tool("lookup_events", {"resource_name": "checkout"})
    [e] = got.structured_content["result"]
    assert e["event"] == "UpdateFunctionConfiguration20150331v2" and e["resources"] == ["checkout"]
    assert len(e["request"]) == aws.EVENT_LIMIT
    assert json.loads(seen[0].content)["LookupAttributes"] == [
        {"AttributeKey": "ResourceName", "AttributeValue": "checkout"}
    ]


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"access_key_id": "ASIAIOSFODNN7EXAMPLE"}, "access_key_id"),  # temporary: expires
        ({"regions": []}, "regions"),
        ({"regions": ["us-east-1/../x"]}, "regions"),
        ({"secret_access_key": "s"}, "Extra inputs"),
    ],
)
def test_an_aws_contract_names_an_iam_users_key_and_its_regions(
    changes: dict[str, Any], error: str
) -> None:
    with pytest.raises(Exception, match=error):
        contracts.build({"id": "a", "name": "a", "integrations": [{**INTEGRATION, **changes}]})


def test_an_aws_contract_must_name_its_regions() -> None:
    no_regions = {k: v for k, v in INTEGRATION.items() if k != "regions"}
    with pytest.raises(Exception, match="regions"):
        contracts.build({"id": "a", "name": "a", "integrations": [no_regions]})


def test_the_key_comes_from_secrets_and_health_reads_alarms() -> None:
    c = contracts.build({"id": "a", "name": "a", "integrations": [INTEGRATION]})
    assert c.secret_refs() == {"aws-key"}
    assert agent.probes(c) == [("aws", "aws_describe_alarms", {"state": "ALARM"})]


@pytest.mark.anyio
async def test_an_aws_scenario_replays_with_its_regions_in_the_guide(settings: Settings) -> None:
    contract = evals.scenario_contract("", False, [Path("no-runbooks")], {}, ["aws"])
    toolbox = evals.replay_server(contract, settings, {"aws_describe_alarms": []})
    async with MCPAdapter(toolbox.mcp) as adapter:
        loaded = await agent.load_tools(adapter, toolbox.access)
    assert {t.name for t in loaded} == {f"aws_{t}" for t in aws.TOOLS}
    assert agent.gated(loaded, toolbox.access) == set()
    assert any("regions us-east-1 (the first is the default)" in g for g in toolbox.guides)
