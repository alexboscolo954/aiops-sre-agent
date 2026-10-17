"""Vendor MCP servers (slice 4.1): started from the Hub's registry as subprocesses,
behind the same allowlist as the builtins (tests/test_agent.py runs those tests on
both), bounded in time, gone after use, and checked by the health page."""

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from fastmcp import Client
from pydantic import SecretStr

from aiops_agent import agent, contracts
from aiops_agent.api import create_app
from aiops_agent.config import Settings
from aiops_agent.servers import vendors
from tests.conftest import REPORT, call, scripted
from tests.test_agent import ALERT, fixture_spec, vendor_contract
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


def test_a_scenario_with_a_vendor_refuses_to_replay_until_snapshots() -> None:
    from aiops_agent import evals

    with pytest.raises(ValueError, match="can't replay integration 'grafana' yet"):
        evals.scenario_contract(
            "", False, [Path("no-runbooks")], {"kind": ["demo"]}, ["kubernetes", "grafana"]
        )


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
