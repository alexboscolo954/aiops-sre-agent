"""Similar incidents: full-text search over the Contract's own finished Triage
Reports, and reading one with what the Operator did about it (slice 7.1)."""

from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from aiops_agent import agent
from aiops_agent.config import Settings
from aiops_agent.models import Investigation
from aiops_agent.servers import incidents
from aiops_agent.store import Store, connect, now
from tests.conftest import REPORT, make_contract

pytestmark = pytest.mark.anyio
DAY = 86400.0


def past(id_: str, summary: str, root_cause: str = "x", **kw: Any) -> Investigation:
    report = {**REPORT, "summary": summary, "probable_root_cause": root_cause}
    fields: dict[str, Any] = {
        "id": id_,
        "contract_id": "acme",
        "title": f"{id_} alert",
        "status": "done",
        "started": now() - DAY,
        "report": report,
        **kw,
    }
    return Investigation.model_validate(fields)


async def search(store: Store, keywords: str, **args: Any) -> dict[str, Any]:
    async with Client(incidents.build_server("acme", store)) as c:
        r = await c.call_tool("search", {"keywords": keywords, **args})
        assert r.structured_content is not None
        return r.structured_content


async def read(store: Store, id_: str) -> dict[str, Any]:
    async with Client(incidents.build_server("acme", store)) as c:
        r = await c.call_tool("read", {"id": id_})
        assert r.structured_content is not None
        return r.structured_content


@pytest.fixture
async def store(database_url: str) -> Any:
    async with connect(database_url) as pool:
        s = Store(pool)
        await s.migrate()
        yield s


async def test_search_finds_the_contracts_past_reports_best_match_first(store: Store) -> None:
    await store.insert(past("one", "reports OOMKilled", "batch size unset"))
    older = now() - 2 * DAY  # the better match is older: only the rank puts it first
    both = past("both", "reports OOMKilled again", "REPORTS_BATCH_SIZE missing, batch")
    await store.insert(both.model_copy(update={"started": older}))
    await store.insert(past("none", "checkout image pull failed"))
    found = (await search(store, "batch REPORTS_BATCH_SIZE oomkilled"))["incidents"]
    assert [f["id"] for f in found] == ["both", "one"]
    first = found[0]
    assert first["summary"] == "reports OOMKilled again"
    assert first["root_cause"] == "REPORTS_BATCH_SIZE missing, batch"
    assert (first["category"], first["confidence"]) == ("resource_limits", "high")
    assert first["title"] == "both alert" and first["date"].endswith(" UTC")


async def test_only_finished_triage_reports_of_this_contract_within_the_window(
    store: Store,
) -> None:
    await store.insert(past("ok", "reports oom"))
    await store.insert(past("bank", "reports oom", contract_id="bank"))
    await store.insert(past("asked", "reports oom", kind="question"))
    await store.insert(past("failed", "reports oom", status="failed"))
    await store.insert(past("running", "reports oom", status="running"))
    await store.insert(past("old", "reports oom", started=now() - 100 * DAY))
    blank = past("blank", "x").model_copy(update={"report": None, "title": "reports oom"})
    await store.insert(blank)
    assert [f["id"] for f in (await search(store, "reports"))["incidents"]] == ["ok"]
    wider = await search(store, "reports", days=365)
    assert {f["id"] for f in wider["incidents"]} == {"ok", "old"}


async def test_any_keyword_text_is_searched_never_parsed(store: Store) -> None:
    await store.insert(past("ok", "reports oom"))
    for odd in ["reports'): & | ! <-> (\"", "a:* & !b", "reports_batch-size", "))", "!!!"]:
        await search(store, odd)  # no error, whatever it finds
    assert [f["id"] for f in (await search(store, '"reports" !'))["incidents"]] == ["ok"]
    nothing = await search(store, "!!! ???")
    assert nothing == {"incidents": [], "note": "No past Report in the last 90 days matches."}


async def test_limits_are_the_tools_own(store: Store) -> None:
    for i in range(4):
        await store.insert(past(f"r{i}", "reports oom"))
    assert len((await search(store, "reports", limit=2))["incidents"]) == 2
    with pytest.raises(ToolError):
        await search(store, "reports", limit=11)
    with pytest.raises(ToolError):
        await search(store, "reports", days=366)


async def test_read_gives_the_report_and_what_the_operator_did(store: Store) -> None:
    t = past("p", "reports oom", "REPORTS_BATCH_SIZE missing").model_copy(
        update={"executed_actions": ["kubernetes_evict_pod shop/reports-1"], "jira_issue": "OPS-7"}
    )
    await store.insert(t)
    evict = [{"name": "kubernetes_evict_pod", "args": {}, "description": "evict"}]
    await store.record_decision("p", False, evict, "Raise nothing: set the batch size", "slack:U1")
    got = await read(store, "p")
    assert got["title"] == "p alert" and got["jira_issue"] == "OPS-7"
    assert "REPORTS_BATCH_SIZE missing" in got["report"]
    assert "kubernetes_evict_pod shop/reports-1" in got["report"]
    assert got["decisions"] == [
        {
            "approved": False,
            "actions": ["kubernetes_evict_pod"],
            "message": "Raise nothing: set the batch size",
            "by": "slack:U1",
        }
    ]


async def test_read_refuses_anything_but_this_contracts_finished_triage(store: Store) -> None:
    await store.insert(past("bank", "x", contract_id="bank"))
    await store.insert(past("asked", "x", kind="question"))
    await store.insert(past("running", "x", status="running"))
    for id_ in ("bank", "asked", "running", "missing"):
        with pytest.raises(ToolError, match=f"no past Report '{id_}' in this Contract"):
            await read(store, id_)


async def test_without_the_hubs_database_the_tools_are_left_out(
    settings: Settings, fake_cluster: Any
) -> None:
    c = make_contract(integrations=[{"name": "kubernetes"}, {"name": "incidents"}])
    cli = agent.build_mcp(c, settings, {"test": fake_cluster})
    assert not any(name.startswith("incidents_") for name in cli.access)
    assert incidents.GUIDE not in cli.guides
    replay = agent.build_mcp(c, settings, {"test": fake_cluster}, snapshots=True)
    assert {"incidents_search", "incidents_read"} <= set(replay.access)
    assert incidents.GUIDE in replay.guides
    async with Client(replay.mcp) as client:
        with pytest.raises(ToolError, match="need the Hub's database"):
            await client.call_tool("incidents_search", {"keywords": "x"})
    assert ("incidents", "incidents_search", {"keywords": "health", "limit": 1}) in agent.probes(c)
