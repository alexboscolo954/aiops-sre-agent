import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from aiops_agent.config import Settings
from aiops_agent.safety import redact, truncate
from aiops_agent.servers import prometheus, runbooks


@pytest.mark.parametrize(
    "secret",
    [
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
        "password=hunter2hunter2",
        'api_key: "abcd1234efgh"',
        "AKIAABCDEFGHIJKLMNOP",
        "sk-proj-abcdefghijklmnopqrstuv",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    ],
)
def test_redact(secret: str) -> None:
    out = redact(f"log line {secret} end")
    assert "[REDACTED]" in out
    assert "log line" in out and "end" in out


def test_redact_keeps_normal_text() -> None:
    line = "GET /api/orders 200 12ms user=42"
    assert redact(line) == line


def test_truncate_keeps_tail_for_logs() -> None:
    out = truncate("a" * 50 + "LAST", 10, keep="tail")
    assert out.endswith("LAST") and "truncated" in out


def prom(handler: Any) -> Client:  # type: ignore[type-arg]
    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://prom")
    settings = Settings(_env_file=None, prometheus_url="http://prom")
    return Client(prometheus.build_server(settings, http))


@pytest.mark.anyio
async def test_prometheus_range_is_summarized() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/v1/query_range"
        data = {
            "resultType": "matrix",
            "result": [{"metric": {"pod": "a"}, "values": [[1, "1"], [2, "5"], [3, "3"]]}],
        }
        return httpx.Response(200, json={"status": "success", "data": data})

    async with prom(handler) as c:
        out = (await c.call_tool("query_range", {"promql": "up"})).structured_content
    assert out["series"][0] == {
        "labels": {"pod": "a"},
        "first": 1.0,
        "last": 3.0,
        "min": 1.0,
        "max": 5.0,
        "points": 3,
    }


@pytest.mark.anyio
async def test_prometheus_error_becomes_tool_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"status": "error", "error": "parse error at char 3"})

    async with prom(handler) as c:
        with pytest.raises(ToolError, match="parse error"):
            await c.call_tool("query", {"promql": "up{"})


@pytest.mark.anyio
async def test_runbooks_match_alert_and_block_paths(tmp_path: Path) -> None:
    (tmp_path / "crashloop.md").write_text(
        "---\ntitle: Crash looping\nalerts: [KubePodCrashLooping]\n---\nRead previous logs.\n"
    )
    (tmp_path / "oom.md").write_text(
        "---\ntitle: OOM\nalerts: [KubePodCrashLooping, ContainerOOMKilled]\n---\nCheck limits.\n"
    )
    settings = Settings(_env_file=None, runbooks_dir=tmp_path)
    async with Client(runbooks.build_server(settings)) as c:
        hit = (
            await c.call_tool("runbook_for_alert", {"alertname": "KubePodCrashLooping"})
        ).structured_content
        names = [b["name"] for b in hit["runbooks"]]
        assert names == ["crashloop", "oom"], names
        assert "previous logs" in hit["runbooks"][0]["content"]
        found = (await c.call_tool("search_runbooks", {"keywords": "logs"})).structured_content
        assert found["result"][0]["name"] == "crashloop"
        with pytest.raises(ToolError, match="unknown runbook"):
            await c.call_tool("read_runbook", {"name": "../../etc/passwd"})


def test_shipped_runbooks_parse() -> None:
    books = runbooks.load(Path(__file__).parent.parent / "runbooks")
    assert books, "runbooks/ is empty"
    for name, book in books.items():
        assert book["alerts"], f"{name} maps to no alert"
        assert len(book["body"]) > 100, name


def test_example_alert_parses() -> None:
    from aiops_agent.models import AlertGroup

    path = Path(__file__).parent.parent / "examples" / "alert-crashloop.json"
    group = AlertGroup.model_validate(json.loads(path.read_text()))
    assert group.firing and group.title.startswith("KubePodCrashLooping")


def test_model_headers_reach_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from aiops_agent.agent import build_model

    monkeypatch.setenv("AIOPS_MODEL_HEADERS", '{"anthropic-workspace-id": "wrkspc_test"}')
    s = Settings(_env_file=None, model_api_key="sk-ant-test")  # type: ignore[arg-type]
    model = build_model(s)
    assert model.default_headers == {"anthropic-workspace-id": "wrkspc_test"}  # type: ignore[attr-defined]
