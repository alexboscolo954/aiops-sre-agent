"""Vendor MCP servers (slice 4.1): started from the Hub's registry as subprocesses,
behind the same allowlist as the builtins (tests/test_agent.py runs those tests on
both), bounded in time, gone after use, and checked by the health page."""

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import anyio
import pytest
import yaml
from fastapi.testclient import TestClient
from fastmcp import Client
from langchain.mcp import MCPAdapter
from pydantic import SecretStr

from aiops_agent import agent, cli, contracts, evals
from aiops_agent.api import create_app
from aiops_agent.config import Settings
from aiops_agent.models import Investigation, TriageReport
from aiops_agent.servers import vendors
from tests.conftest import REPORT, call, scripted
from tests.test_agent import ALERT, LIST, fixture_spec, vendor_contract
from tests.test_console import OPERATOR, VIEW


def test_a_vendor_must_be_in_the_hubs_registry_and_probe_only_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def problems(**v: Any) -> str:
        with pytest.raises(Exception) as e:
            vendor_contract(monkeypatch, **v)
        return str(e.value)

    monkeypatch.setitem(vendors.VENDORS, "fixture", fixture_spec())
    unknown = {"name": "x", "vendor": "nope", "tools": {"peek": "read"}}
    with pytest.raises(Exception, match="vendor 'nope' isn't in the Hub's registry"):
        contracts.build({"id": "a", "name": "a", "integrations": [unknown]})
    assert "probe tool 'sneaky' must be listed in tools as read" in problems(
        probe={"tool": "sneaky"}
    )
    assert "must be listed in tools as read" in problems(probe={"tool": "unlisted"})
    with pytest.raises(Exception, match="unknown integration 'kubernets'"):
        contracts.build({"id": "a", "name": "a", "integrations": [{"name": "kubernets"}]})


def test_env_secrets_are_checked_like_every_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    c = vendor_contract(monkeypatch, env_secrets={"TOKEN": "grafana-token"})
    assert c.secret_refs() == {"grafana-token"}


@pytest.mark.anyio
async def test_a_vendor_process_never_outlives_its_use(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    toolbox = agent.build_mcp(vendor_contract(monkeypatch), settings)
    async with Client(toolbox.mcp) as client:
        result = await client.call_tool("x_environment", {})
        pid = int(json.loads(result.content[0].text)["PID"])
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        await anyio.sleep(0.05)
    pytest.fail(f"vendor process {pid} still running")


SNAPSHOTS = Path(__file__).parent / "fixtures" / "snapshots"
CHECK = ["integrations", "snapshot", "fixture", "--check"]


@pytest.fixture
def snapshots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """The fixture vendor in the registry, with its snapshot in a scratch copy of
    tests/fixtures/snapshots (for tests that change or delete it)."""
    monkeypatch.setitem(vendors.VENDORS, "fixture", fixture_spec())
    shutil.copytree(SNAPSHOTS, tmp_path, dirs_exist_ok=True)
    monkeypatch.setattr(vendors, "SNAPSHOTS", tmp_path)
    return tmp_path


@pytest.mark.anyio
async def test_the_committed_snapshot_matches_the_running_vendor(snapshots: Path) -> None:
    """The slice 4.2 check, here on the fixture; on a registry vendor it's
    `aiops integrations snapshot <name> --check`, run where its pinned binary is."""
    if os.environ.get("AIOPS_UPDATE_FIXTURE_SNAPSHOT"):
        (SNAPSHOTS / "fixture.json").write_text(await vendors.capture(fixture_spec()))
        shutil.copy(SNAPSHOTS / "fixture.json", snapshots)
    assert await vendors.drift("fixture") == "", (
        "the fixture vendor's tools changed (a fastmcp upgrade?): review the diff, then "
        "rerun with AIOPS_UPDATE_FIXTURE_SNAPSHOT=1"
    )


@pytest.mark.parametrize(
    "saved,live",
    [
        ('"name": "glance"', '"name": "peek"'),  # the vendor renamed glance to peek
        ("Takes one argument", "Takes an argument"),  # the model reads descriptions
    ],
)
def test_check_fails_on_a_renamed_or_redescribed_tool(
    snapshots: Path, capfd: pytest.CaptureFixture[str], saved: str, live: str
) -> None:
    path = snapshots / "fixture.json"
    assert cli.main(CHECK) == 0
    path.write_text(path.read_text().replace(live, saved))
    capfd.readouterr()
    assert cli.main(CHECK) == 1
    out = capfd.readouterr()
    lines = out.out.splitlines()
    assert any(line.startswith("-") and saved in line for line in lines)
    assert any(line.startswith("+") and live in line for line in lines)
    assert "Run `aiops integrations snapshot fixture`" in out.err


def test_snapshot_writes_what_check_accepts(snapshots: Path) -> None:
    (snapshots / "fixture.json").unlink()
    assert cli.main(CHECK) == 1  # no snapshot yet: everything is drift
    assert cli.main(["integrations", "snapshot", "fixture"]) == 0
    assert (snapshots / "fixture.json").read_text() == (SNAPSHOTS / "fixture.json").read_text()
    assert cli.main(CHECK) == 0


def test_every_registry_vendor_has_a_snapshot(snapshots: Path) -> None:
    def missing() -> list[str]:
        return [v for v in vendors.VENDORS if not (vendors.SNAPSHOTS / f"{v}.json").exists()]

    assert missing() == []  # the fixture, plus every real vendor once there is one
    (snapshots / "fixture.json").unlink()
    assert missing() == ["fixture"]


ECHO = """\
import json, os
from fastmcp import FastMCP
mcp = FastMCP("echo")
@mcp.tool(description=json.dumps(dict(os.environ)))
def env() -> str:
    return ""
mcp.run(show_banner=False)
"""


@pytest.mark.anyio
async def test_a_snapshot_never_sees_the_hubs_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """Snapshots are committed to a public repo: a vendor that writes its config into
    a description must find none of the Hub's in its environment."""
    monkeypatch.setenv("AIOPS_SLACK_BOT_TOKEN", "xoxb-sentinel-123")
    snap = json.loads(
        await vendors.capture(vendors.Spec((sys.executable, "-c", ECHO), frozenset()))
    )
    seen = json.loads(snap[0]["description"])
    assert "PATH" in seen  # the echo works: MCP's safe defaults are there
    assert "AIOPS_SLACK_BOT_TOKEN" not in seen


EVERY = {**LIST, "lookup": "read", "environment": "read"}


@pytest.mark.anyio
async def test_replay_offers_the_vendor_tools_as_the_real_vendor_does(
    settings: Settings, snapshots: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the agent gets: names, descriptions, argument schemas and the approval
    gate (from annotations), the same from the snapshot as from the subprocess."""
    c = vendor_contract(monkeypatch, EVERY)

    async def seen(toolbox: agent.Toolbox) -> tuple[dict[str, Any], set[str]]:
        async with MCPAdapter(toolbox.mcp) as adapter:
            tools = await agent.load_tools(adapter, toolbox.access)
        offered = {t.name: (t.description, t.args_schema, t.metadata) for t in tools}
        return offered, agent.gated(tools, toolbox.access)

    real = await seen(agent.build_mcp(c, settings))
    assert await seen(agent.build_mcp(c, settings, snapshots=True)) == real
    assert len(real[0]) == len(EVERY)
    assert real[1] == {"x_sneaky", "x_honest", "x_unknown"}


@pytest.mark.anyio
async def test_a_saved_vendor_investigation_replays_to_the_same_results(
    settings: Settings, snapshots: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Record a Run against the real vendor, save it as a Scenario, replay that from
    the snapshot with no vendor process: same calls, same results, a string and a
    dict tool. The Scenario keeps which vendor and the Hub's list, never its env."""
    tools = {"lookup": "read", "environment": "read"}
    c = vendor_contract(monkeypatch, tools, env={"TOKEN": "tok-sentinel"})
    steps = [
        call("x_lookup", "a", service="api"),
        call("x_environment", "b"),
        call("TriageReport", "r", **REPORT),
    ]

    async def run(toolbox: agent.Toolbox) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []

        async def sink(tool: str, args: dict[str, Any], result: str, is_error: bool) -> None:
            rows.append({"tool": tool, "args": args, "result": result, "is_error": is_error})

        async with agent.open_agent(settings, toolbox, scripted(*steps), record=sink) as a:
            assert (await agent.start(a, ALERT, "v")).report is not None
        return rows

    recorded = await run(agent.build_mcp(c, settings))
    assert recorded[0]["result"] == "lookup api ran"
    assert "tok-sentinel" not in recorded[1]["result"]  # redacted when recorded (2.6)
    t = Investigation(
        id="v",
        contract_id="acme",
        title="t",
        started=0,
        status="done",
        kind="triage",
        input={"status": "firing", "alerts": []},
        report=TriageReport(**REPORT),
    )
    text = evals.scenario_yaml(t, c, recorded, [])
    scenario = yaml.safe_load(text)
    assert scenario["integrations"] == [{"name": "x", "vendor": "fixture", "tools": tools}]
    assert "tok-sentinel" not in text  # its env isn't part of the Scenario

    monkeypatch.setitem(vendors.VENDORS, "fixture", vendors.Spec(("/nonexistent",), frozenset()))
    replayed = evals.scenario_contract(
        "", False, [Path("no-runbooks")], scenario["clusters"], scenario["integrations"]
    )

    # Same content, not byte for byte the same JSON (a known limit of scenario_yaml).
    def parsed(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{**r, "result": evals._result(r["result"])} for r in rows]

    replayed_rows = await run(evals.replay_server(replayed, settings, scenario["tools"]))
    assert parsed(replayed_rows) == parsed(recorded)


@pytest.mark.anyio
async def test_replay_checks_vendor_arguments_against_the_snapshot(
    settings: Settings, snapshots: Path
) -> None:
    vendor = {"name": "x", "vendor": "fixture", "tools": {"lookup": "read"}}
    contract = evals.scenario_contract("", False, [Path("no-runbooks")], {}, [vendor])
    toolbox = evals.replay_server(contract, settings, {"x_lookup": "up"})
    async with Client(toolbox.mcp) as client:
        missing = await client.call_tool("x_lookup", {}, raise_on_error=False)
        ok = await client.call_tool("x_lookup", {"service": "api"})
    assert missing.is_error and "'service' is a required property" in missing.content[0].text
    assert ok.content[0].text == "up"


@pytest.mark.anyio
async def test_a_vendor_that_never_answers_cannot_hold_a_run(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        vendors.VENDORS,
        "hang",
        vendors.Spec((sys.executable, "-c", "import time; time.sleep(60)"), frozenset()),
    )
    monkeypatch.setattr(vendors, "START_SECONDS", 1)
    hang = {"name": "x", "vendor": "hang", "tools": {"peek": "read"}}
    c = contracts.build({"id": "a", "name": "a", "integrations": [hang]})
    start = time.monotonic()
    model = scripted(call("TriageReport", "r", **REPORT))
    async with agent.open_agent(settings, agent.build_mcp(c, settings), model) as a:
        outcome = await agent.start(a, ALERT, "h")
    assert outcome.report is not None  # the Run went on without the vendor's tools
    assert time.monotonic() - start < 15


def test_health_checks_a_vendor_starts_and_offers_its_listed_tools(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    settings.approver_token = SecretStr("approver-token")
    monkeypatch.setitem(vendors.VENDORS, "fixture", fixture_spec())

    def contract(cid: str, **v: Any) -> contracts.Contract:
        vendor = {"name": "x", "vendor": "fixture", **v}
        return contracts.build({"id": cid, "name": cid, "integrations": [vendor]})

    by_id = {
        "listed": contract("listed", tools={"peek": "read"}),
        "renamed": contract("renamed", tools={"peek": "read", "ghost": "read"}),
        "probed": contract("probed", tools={"peek": "read"}, probe={"tool": "peek"}),
    }

    def mcp(c: contracts.Contract) -> agent.Toolbox:
        return agent.build_mcp(c, settings)

    with TestClient(create_app(settings, scripted(), mcp, by_id)) as c:
        page = c.get("/console/health", headers=VIEW).text

    def row(cid: str) -> str:
        start = page.index(f"<h2><code>{cid}</code>")
        return page[start : page.find("<h2>", start + 1)]

    assert "<td>x</td><td>ok</td>" in row("listed")
    assert "<td>x</td><td>FAILING</td>" in row("renamed") and "not offered: x_ghost" in row(
        "renamed"
    )
    assert "<td>x</td><td>ok</td>" in row("probed")


def test_a_scenario_vendor_needs_its_vendor_and_a_snapshot(snapshots: Path) -> None:
    """A vendor saved by name only (a draft from before 4.2) can't say which vendor's
    snapshot to use; a vendor with no snapshot has no tools to offer."""
    with pytest.raises(ValueError, match="can't replay integration 'grafana': a vendor needs"):
        evals.scenario_contract(
            "", False, [Path("no-runbooks")], {"kind": ["demo"]}, ["kubernetes", "grafana"]
        )
    (snapshots / "fixture.json").unlink()
    vendor = {"name": "x", "vendor": "fixture", "tools": {"peek": "read"}}
    contract = evals.scenario_contract("", False, [Path("no-runbooks")], {}, [vendor])
    with pytest.raises(ValueError, match="no schema snapshot for vendor 'fixture'"):
        evals.replay_server(contract, Settings(), {})


@pytest.mark.parametrize(
    "field,name",
    [
        ("env", "LD_PRELOAD"),
        ("env", "PATH"),
        ("env", "NODE_OPTIONS"),
        ("env_secrets", "PYTHONPATH"),
    ],
)
def test_a_contract_sets_only_the_variables_its_vendor_lists(
    monkeypatch: pytest.MonkeyPatch, field: str, name: str
) -> None:
    """Any other variable could make the vendor run code of the contracts repo's choosing."""
    with pytest.raises(
        Exception, match=f"takes only these variables: RAN_FILE, TOKEN; refused: {name}"
    ):
        vendor_contract(monkeypatch, **{field: {name: "x"}})


def test_a_registry_command_must_be_an_absolute_path() -> None:
    with pytest.raises(ValueError, match="absolute path: 'mcp-grafana'"):
        vendors.Spec(("mcp-grafana",), frozenset())


@pytest.mark.anyio
async def test_a_snapshot_tool_reached_without_a_recording_fails_loudly(snapshots: Path) -> None:
    async with Client(vendors.snapshot_server("fixture", "x")) as client:
        result = await client.call_tool("peek", {}, raise_on_error=False)
    assert result.is_error and "peek is a snapshot" in result.content[0].text
