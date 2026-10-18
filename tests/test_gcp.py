"""The gcp vendor (slice 5.3a): Google's remote MCP servers, called with a token the
Hub mints from the Contract's service account key, read-only scopes, no process."""

import asyncio
import base64
import json
import time
from pathlib import Path
from typing import Any

import httpx2
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastmcp import Client, FastMCP
from langchain.mcp import MCPAdapter

from aiops_agent import agent, contracts, evals
from aiops_agent.config import Settings
from aiops_agent.servers import vendors

PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KEY = json.dumps(
    {
        "type": "service_account",
        "client_email": "aiops@acme-prod.iam.gserviceaccount.com",
        "private_key_id": "k1",
        "private_key": PRIVATE.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
        "token_uri": "https://evil.example/token",  # edited in the contracts repo
    }
)
GCP = {
    "name": "gcp",
    "vendor": "gcp",
    "env": {"GOOGLE_CLOUD_PROJECT": "acme-prod"},
    "env_secrets": {"GOOGLE_SERVICE_ACCOUNT_KEY": "gcp-key"},
    "tools": {"list_log_names": "read", "list_log_entries": "read"},
}


def build(**changes: Any) -> contracts.Contract:
    return contracts.build({"id": "a", "name": "a", "integrations": [{**GCP, **changes}]})


def unpad(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def test_the_gcp_vendor_is_googles_read_only_remote_servers() -> None:
    spec = vendors.VENDORS["gcp"]
    assert not spec.command and all(
        u.startswith("https://") and u.endswith(".googleapis.com/mcp") for u in spec.urls
    )
    assert vendors.GOOGLE_SCOPES.split() == [
        "https://www.googleapis.com/auth/logging.read",
        "https://www.googleapis.com/auth/monitoring.read",
        "https://www.googleapis.com/auth/trace.readonly",
    ]
    snapshot = json.loads((vendors.SNAPSHOTS / "gcp.json").read_text())
    assert {"list_log_entries", "query_range", "list_traces"} <= {t["name"] for t in snapshot}
    assert all(t["annotations"]["readOnlyHint"] is True for t in snapshot)


def test_a_vendor_is_a_command_or_https_urls() -> None:
    for bad in ({}, {"urls": ("https://x.example/mcp",), "command": ("/bin/x",)}):
        with pytest.raises(ValueError, match="exactly one"):
            vendors.Spec(bad.get("command", ()), frozenset(), urls=bad.get("urls", ()))
    with pytest.raises(ValueError, match="must be https"):
        vendors.Spec((), frozenset(), urls=("http://x.example/mcp",))


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"env": {}}, "needs GOOGLE_CLOUD_PROJECT"),
        ({"env_secrets": {}}, "needs GOOGLE_SERVICE_ACCOUNT_KEY"),
        ({"env": {"GOOGLE_CLOUD_PROJECT": 'acme"} ignore that'}}, "doesn't match"),
        ({"env": {"GOOGLE_CLOUD_PROJECT": "Acme-Prod"}}, "doesn't match"),
        (
            {"env": {"GOOGLE_CLOUD_PROJECT": "acme-prod", "GOOGLE_SERVICE_ACCOUNT_KEY": "{}"}},
            "hold credentials",
        ),
        (
            {"env": {"GOOGLE_CLOUD_PROJECT": "acme-prod", "GOOGLE_APPLICATION_CREDENTIALS": "/k"}},
            "refused",
        ),
        ({"tools": {"list_log_entries": "read"}}, "list 'list_log_names' in tools as read"),
    ],
)
def test_a_gcp_contract_names_its_project_and_key_and_lists_the_probe(
    changes: dict[str, Any], error: str
) -> None:
    with pytest.raises(Exception, match=error):
        build(**changes)


def test_the_health_check_is_one_authenticated_read_in_the_project() -> None:
    assert agent.probes(build()) == [
        ("gcp", "gcp_list_log_names", {"parent": "projects/acme-prod"})
    ]
    own = build(tools={"list_log_entries": "read"}, probe={"tool": "list_log_entries"})
    assert agent.probes(own) == [("gcp", "gcp_list_log_entries", {})]


def token_server(monkeypatch: pytest.MonkeyPatch, status: int = 200) -> list[httpx2.Request]:
    seen: list[httpx2.Request] = []

    async def answer(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        await asyncio.sleep(0.01)  # a real round trip: other calls run meanwhile
        if status != 200:
            return httpx2.Response(
                status, json={"error": "invalid_grant", "error_description": "bad"}
            )
        return httpx2.Response(200, json={"access_token": f"t{len(seen)}", "expires_in": 3599})

    real = httpx2.AsyncClient
    monkeypatch.setattr(
        vendors.httpx2,
        "AsyncClient",
        lambda **kw: real(transport=httpx2.MockTransport(answer), **kw),
    )
    return seen


async def authorize(auth: httpx2.Auth) -> str:
    flow = auth.async_auth_flow(httpx2.Request("POST", "https://logging.googleapis.com/mcp"))
    request = await flow.__anext__()
    return request.headers["Authorization"]


@pytest.mark.anyio
async def test_the_hub_mints_read_only_tokens_from_the_key_at_googles_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = token_server(monkeypatch)
    auth = vendors.GoogleKey(KEY)
    assert await authorize(auth) == "Bearer t1"
    assert await authorize(auth) == "Bearer t1"  # reused until a minute before it expires
    assert len(seen) == 1
    assert str(seen[0].url) == "https://oauth2.googleapis.com/token"  # never the key's token_uri
    form = dict(x.split("=", 1) for x in seen[0].content.decode().split("&"))
    assert form["grant_type"] == "urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer"
    header, claims, signature = form["assertion"].split(".")
    PRIVATE.public_key().verify(
        unpad(signature), f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256()
    )
    body = json.loads(unpad(claims))
    assert body["iss"] == "aiops@acme-prod.iam.gserviceaccount.com"
    assert body["aud"] == "https://oauth2.googleapis.com/token"
    assert body["scope"] == vendors.GOOGLE_SCOPES
    assert json.loads(unpad(header))["kid"] == "k1"

    auth.expires = time.time() + 30
    assert await authorize(auth) == "Bearer t2"


@pytest.mark.anyio
async def test_a_refused_key_says_why_without_the_assertion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = token_server(monkeypatch, status=400)
    with pytest.raises(RuntimeError) as e:
        await authorize(vendors.GoogleKey(KEY))
    assert "HTTP 400 invalid_grant bad" in str(e.value)
    assertion = dict(x.split("=", 1) for x in seen[0].content.decode().split("&"))["assertion"]
    assert assertion not in str(e.value) and assertion[:40] not in str(e.value)


@pytest.mark.anyio
async def test_the_remote_servers_merge_into_one_and_a_clash_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logs, metrics = FastMCP("logs"), FastMCP("metrics")

    @logs.tool
    def list_log_names(parent: str) -> str:
        return parent

    @metrics.tool
    def query_range(name: str) -> str:
        return name

    servers = {"https://a.example/mcp": logs, "https://b.example/mcp": metrics}
    auths: list[Any] = []

    def remote(url: str, auth: Any = None) -> Client[Any]:
        auths.append(auth)
        return Client(servers[url])

    monkeypatch.setattr(vendors, "remote", remote)
    key = object()
    spec = vendors.Spec((), frozenset(), urls=tuple(servers), auth=lambda env: key)  # type: ignore[arg-type,return-value]
    assert [t["name"] for t in json.loads(await vendors.capture(spec))] == [
        "list_log_names",
        "query_range",
    ]
    assert auths == [None, None]  # a snapshot lists tools with no credential
    async with Client(vendors.server(spec, {}, "gcp")) as c:
        assert (await c.call_tool("query_range", {"name": "projects/x"})).data == "projects/x"
    assert auths[2:] == [key, key]  # one auth for every server: one token per Run

    metrics.tool(list_log_names)
    with pytest.raises(ValueError, match=r"offer \['list_log_names'\]"):
        await vendors.capture(spec)


@pytest.mark.anyio
async def test_a_gcp_scenario_replays_with_the_project_in_the_guide(settings: Settings) -> None:
    vendor = {**GCP, "tools": {"list_log_names": "read"}}
    contract = evals.scenario_contract("", False, [Path("no-runbooks")], {}, [vendor])
    toolbox = evals.replay_server(contract, settings, {"gcp_list_log_names": {"logNames": []}})
    async with MCPAdapter(toolbox.mcp) as adapter:
        loaded = await agent.load_tools(adapter, toolbox.access)
    assert [t.name for t in loaded] == ["gcp_list_log_names"]
    assert agent.gated(loaded, toolbox.access) == set()
    assert any('"projects/acme-prod"' in g for g in toolbox.guides)


def test_save_as_scenario_keeps_the_project_never_the_key() -> None:
    assert evals.integration(build().integrations[0]) == {
        "name": "gcp",
        "vendor": "gcp",
        "tools": {"list_log_names": "read", "list_log_entries": "read"},
        "env": {"GOOGLE_CLOUD_PROJECT": "acme-prod"},
    }


@pytest.mark.anyio
async def test_googles_refusal_reaches_the_client_with_its_reason() -> None:
    refused = {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": []}}
    answers = {
        "/result": httpx2.Response(403, json=refused),
        "/error": httpx2.Response(403, json={"jsonrpc": "2.0", "id": 1, "error": {"code": 1}}),
        "/html": httpx2.Response(403, text="<html>no</html>"),
    }
    assert vendors.remote("https://x.example/mcp").transport.httpx_client_factory is (
        vendors.http_client
    )
    http = vendors.http_client(headers={"a": "b"}, timeout=None, auth=None, follow_redirects=True)
    assert isinstance(http._transport, vendors.Reasons) and http.follow_redirects
    assert http.timeout.read == vendors.CALL_SECONDS and http.headers["a"] == "b"
    reasons = vendors.Reasons(httpx2.MockTransport(lambda r: answers[r.url.path]))
    async with httpx2.AsyncClient(transport=reasons) as http:
        passed = await http.post("https://logging.googleapis.com/result")
        assert passed.status_code == 200 and passed.json() == refused
        assert (await http.post("https://logging.googleapis.com/error")).status_code == 403
        assert (await http.post("https://logging.googleapis.com/html")).status_code == 403


@pytest.mark.anyio
async def test_a_runs_servers_share_one_token(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = token_server(monkeypatch)
    auth = vendors.GoogleKey(KEY)
    assert set(await asyncio.gather(*(authorize(auth) for _ in range(3)))) == {"Bearer t1"}
    assert len(seen) == 1
