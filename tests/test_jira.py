"""The Jira builtin (slice 4.4): past issues of the Contract's own project as Evidence.
Responses are synthetic, in Jira Cloud REST v3's documented shapes."""

import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastmcp import Client
from pydantic import SecretStr

from aiops_agent import agent, contracts, evals
from aiops_agent.config import Settings
from aiops_agent.servers import jira
from tests.conftest import REPORT, call, scripted
from tests.test_agent import ALERT

URL = "https://acme.atlassian.net"
INTEGRATION = {
    "name": "jira",
    "url": URL,
    "email": "sre@acme.example",
    "token_secret": "jira-token",
    "project": "OPS",
}


def adf(*paragraphs: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": p}]} for p in paragraphs
        ],
    }


ISSUE = {
    "key": "OPS-42",
    "fields": {
        "summary": "payments 502s: fraud-check refused connections",
        "status": {"name": "Done"},
        "resolution": {"name": "Fixed"},
        "created": "2026-08-01T10:00:00.000+0000",
        "resolutiondate": "2026-08-01T12:30:00.000+0000",
        "labels": ["incident"],
        "project": {"key": "OPS"},
        "description": adf("fraud-check pods were OOMKilled.", "Raised its memory limit."),
        "comment": {
            "comments": [
                {"author": {"displayName": f"sre{n}"}, "created": "x", "body": adf(f"note {n}")}
                for n in range(7)
            ]
        },
    },
}


class Jira:
    """A fake Jira Cloud: records requests, answers from `issues` by key."""

    def __init__(self, issues: dict[str, dict[str, Any]] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.issues = issues if issues is not None else {"OPS-42": ISSUE}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/rest/api/3/search/jql":
            return httpx.Response(200, json={"issues": list(self.issues.values()), "isLast": True})
        key = request.url.path.rsplit("/", 1)[-1]
        if key in self.issues:
            return httpx.Response(200, json=self.issues[key])
        return httpx.Response(404, json={"errorMessages": ["Issue does not exist"]})

    def server(self) -> Any:
        http = httpx.Client(base_url=URL, transport=httpx.MockTransport(self))
        return jira.build_server(URL, "sre@acme.example", SecretStr("t"), "OPS", http)


@pytest.mark.anyio
async def test_search_stays_inside_the_contracts_project() -> None:
    """The model passes words; the server writes the JQL. An injection attempt can't
    add a clause, and a hyphenated name becomes words Jira's text search finds."""
    fake = Jira()
    async with Client(fake.server()) as c:
        found = await c.call_tool(
            "search_issues", {"text": 'fraud-check" OR project = BANK OR text ~ "x'}
        )
    (request,) = fake.requests
    jql = json.loads(request.content)["jql"]
    assert jql == (
        'project = "OPS" AND text ~ "fraud check OR project BANK OR text x" '
        "AND created >= -365d ORDER BY created DESC"
    )
    assert jql.count('"') == 4 and jql.count("project =") == 1
    assert found.structured_content["result"][0]["url"] == f"{URL}/browse/OPS-42"


@pytest.mark.anyio
async def test_get_issue_reads_one_issue_of_the_project_as_text() -> None:
    async with Client(Jira().server()) as c:
        issue = (await c.call_tool("get_issue", {"key": "OPS-42"})).structured_content
    assert issue["description"] == "fraud-check pods were OOMKilled.\nRaised its memory limit."
    assert issue["resolution"] == "Fixed"
    assert [c["body"] for c in issue["comments"]] == [f"note {n}" for n in range(2, 7)]


@pytest.mark.anyio
async def test_get_issue_refuses_other_projects_and_odd_keys() -> None:
    moved = {**ISSUE, "key": "OPS-7", "fields": {**ISSUE["fields"], "project": {"key": "BANK"}}}
    fake = Jira({"OPS-7": moved})
    async with Client(fake.server()) as c:
        other = await c.call_tool("get_issue", {"key": "OPS-7"}, raise_on_error=False)
        odd = await c.call_tool("get_issue", {"key": "../../myself"}, raise_on_error=False)
    assert other.is_error and "not in this Contract's Jira project" in other.content[0].text
    assert odd.is_error and "not an issue key" in odd.content[0].text
    assert [r.url.path for r in fake.requests] == ["/rest/api/3/issue/OPS-7"]  # odd: no call


@pytest.mark.anyio
async def test_jira_errors_name_the_status_never_the_credentials() -> None:
    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"errorMessages": ["Client must be authenticated"]})

    http = httpx.Client(base_url=URL, transport=httpx.MockTransport(denied))
    server = jira.build_server(URL, "sre@acme.example", SecretStr("s3cret-token"), "OPS", http)
    async with Client(server) as c:
        r = await c.call_tool("search_issues", {"text": "x"}, raise_on_error=False)
    assert r.is_error and r.content[0].text == "Jira error 401: Client must be authenticated"


def test_the_contract_names_an_https_jira_and_a_project_key() -> None:
    def build(**over: Any) -> contracts.Contract:
        return contracts.build({"id": "a", "name": "a", "integrations": [{**INTEGRATION, **over}]})

    assert build().secret_refs() == {"jira-token"}
    with pytest.raises(Exception, match="String should match pattern"):
        build(url="http://acme.atlassian.net")
    with pytest.raises(Exception, match="String should match pattern"):
        build(project='OPS" OR project = BANK')


def test_each_contract_uses_its_own_jira_credentials(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, str]] = []

    class Recorder:
        def __init__(self, base_url: str, auth: tuple[str, str], **_: Any) -> None:
            seen.append((base_url, base64.b64encode(":".join(auth).encode()).decode()))

    monkeypatch.setattr(jira.httpx, "Client", Recorder)
    for cid, token in (("shop", "shop-token"), ("bank", "bank-token")):
        integration = {**INTEGRATION, "url": f"https://{cid}.atlassian.net"}
        c = contracts.build(
            {"id": cid, "name": cid, "integrations": [integration]},
            secrets={"jira-token": SecretStr(token)},
        )
        agent.build_mcp(c, settings)
    assert seen == [
        ("https://shop.atlassian.net", base64.b64encode(b"sre@acme.example:shop-token").decode()),
        ("https://bank.atlassian.net", base64.b64encode(b"sre@acme.example:bank-token").decode()),
    ]


def test_jira_has_a_health_check_and_a_guide_only_when_present(settings: Settings) -> None:
    c = contracts.build(
        {"id": "a", "name": "a", "integrations": [INTEGRATION]},
        secrets={"jira-token": SecretStr("t")},
    )
    assert agent.probes(c) == [
        ("jira", "jira_search_issues", {"text": "health", "days": 1, "limit": 1})
    ]
    toolbox = agent.build_mcp(c, settings)
    assert set(toolbox.access) == {"jira_search_issues", "jira_get_issue"}
    assert agent.prompt("triage", toolbox) == agent.SYSTEM_PROMPT + "\n" + jira.GUIDE


@pytest.mark.anyio
async def test_a_saved_jira_investigation_replays(settings: Settings) -> None:
    """Save as Scenario names the builtin; replay offers its tools with a placeholder
    Contract that has no secrets, and answers from the recording."""
    from aiops_agent.models import Investigation, TriageReport

    c = contracts.build(
        {"id": "a", "name": "a", "integrations": [INTEGRATION]},
        secrets={"jira-token": SecretStr("t")},
    )
    t = Investigation(
        id="j", contract_id="a", title="t", started=0, status="done", kind="triage",
        input={"status": "firing", "alerts": []}, report=TriageReport(**REPORT),
    )  # fmt: skip
    row = {"tool": "jira_search_issues", "args": {"text": "payments"}, "result": "[]"}
    scenario = yaml.safe_load(evals.scenario_yaml(t, c, [{**row, "is_error": False}], []))
    assert scenario["integrations"] == ["jira"]
    replayed = evals.scenario_contract(
        "", False, [Path("no-runbooks")], scenario["clusters"], scenario["integrations"]
    )
    model = scripted(
        call("jira_search_issues", "s", text="payments"), call("TriageReport", "r", **REPORT)
    )
    rows: list[str] = []

    async def sink(tool: str, args: dict[str, Any], result: str, is_error: bool) -> None:
        rows.append(f"{tool} {result} {is_error}")

    toolbox = evals.replay_server(replayed, settings, scenario["tools"])
    async with agent.open_agent(settings, toolbox, model, record=sink) as a:
        await agent.start(a, ALERT, "j")
    assert rows == ["jira_search_issues [] False"]
