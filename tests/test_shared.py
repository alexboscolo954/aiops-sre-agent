"""Shared knowledge (slice 7.2): `shared/` in the contracts repo, read by every
Contract. It must hold no client data, and the agent has no write path to it."""

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastmcp import Client
from fastmcp.exceptions import ToolError
from pydantic import SecretStr

from aiops_agent import agent, contracts
from aiops_agent.config import Settings
from tests.test_contracts import BASE, problems, write

ROOT = Path(__file__).parent.parent
FULL: dict[str, Any] = {
    **BASE,
    "name": "Acme Payments",
    "clusters": [{"name": "prod", "context": "acme-eks-prod", "namespaces": ["shop"]}],
    "integrations": [
        {"name": "kubernetes"},
        {"name": "prometheus", "url": "https://prom.acme-corp.io/"},
        {
            "name": "jira",
            "url": "https://acmecorp.atlassian.net",
            "email": "sre@example.com",
            "token_secret": "jira",
            "project": "PAYOPS",
        },
        {
            "name": "aws",
            "regions": ["us-east-1"],
            "access_key_id": "AKIAACMEACMEACMEACME",
            "secret_access_key_secret": "aws",
        },
        {
            "name": "gcp",
            "vendor": "gcp",
            "env": {"GOOGLE_CLOUD_PROJECT": "acme-shop-4f2a"},
            "env_secrets": {"GOOGLE_SERVICE_ACCOUNT_KEY": "gcp"},
            "tools": {"list_log_names": "read"},
        },
    ],
    "slack": {"operator_channel": "C0ACMEOPS1", "client_channel": "C0ACMECLI1"},
}


def shared(root: Path, text: str) -> Path:
    path = root / "shared" / "runbooks" / "lesson.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntitle: A lesson\n---\nFirst line.\n{text}\n")
    return path


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """FULL as a Contract whose secrets need no decryption."""
    monkeypatch.setattr(contracts, "_decrypt", lambda _: {"jira": "x", "aws": "x", "gcp": "{}"})
    monkeypatch.setattr(contracts, "_recipients", lambda _: set())
    write(tmp_path, FULL)
    (tmp_path / "acme" / contracts.SECRETS_FILE).write_text("sops: {}\n")
    return tmp_path


@pytest.mark.parametrize(
    ("text", "what"),
    [
        ("Ask the acme team first.", "id"),
        ("Seen at acme payments last spring.", "name"),
        ("kubectl --context acme-eks-prod get pods", "kube context"),
        ("Query https://prom.acme-corp.io/graph for it.", "prometheus host"),
        ("See acmecorp.atlassian.net.", "jira host"),
        ("File it in PAYOPS.", "Jira project"),
        ("Key AKIAACMEACMEACMEACME was rotated.", "AWS access key id"),
        ("Post in C0ACMEOPS1.", "operator channel"),
        ("Tell C0ACMECLI1.", "client channel"),
        ("Logs live in project acme-shop-4f2a.", "gcp GOOGLE_CLOUD_PROJECT"),
    ],
)
def test_a_shared_file_naming_a_contract_is_refused(repo: Path, text: str, what: str) -> None:
    path = shared(repo, text)
    assert (
        f"{path}:5: names Contract 'acme' (its {what}): Shared knowledge is read by every "
        "Contract and must hold no client data"
    ) in problems(repo)


@pytest.mark.parametrize(
    "text",
    [
        "Restart pods in namespace shop on cluster prod.",  # generic names: not checked
        "The acmeville, notacme and acme-like services, and x.acme.example.",  # not words
        "Use OPS and SRE runbooks.",  # short terms: not checked
    ],
)
def test_generic_text_is_not_refused(repo: Path, text: str) -> None:
    shared(repo, text)
    assert "acme" in contracts.load(repo)


def test_terms_under_four_characters_are_not_checked() -> None:
    """A Jira project like OPS is also a common word."""
    data = copy.deepcopy(FULL)
    data["integrations"][2]["project"] = "OPS"
    secrets = {k: SecretStr("x") for k in ("jira", "aws", "gcp")}
    c = contracts.build(data, secrets=secrets)
    assert "OPS" not in contracts.identifiers(c)
    assert contracts.identifiers(c)["acme"] == "id"


@pytest.mark.parametrize(
    "url",
    [
        "http://prometheus:9090",
        "http://localhost:9090",
        "http://10.0.0.5:9090",
        "http://prometheus-operated.monitoring.svc:9090",
        "http://prom.monitoring.svc.cluster.local",
    ],
)
def test_a_generic_host_is_no_identifier(url: str) -> None:
    """Hosts every client's setup can share would refuse ordinary text."""
    data = copy.deepcopy(FULL)
    data["integrations"][1]["url"] = url
    secrets = {k: SecretStr("x") for k in ("jira", "aws", "gcp")}
    found = contracts.identifiers(contracts.build(data, secrets=secrets))
    assert "prometheus host" not in found.values()


def test_generic_hosts_in_shared_text_load(repo: Path) -> None:
    data = copy.deepcopy(FULL)
    data["integrations"][1]["url"] = "http://prometheus:9090"
    write(repo, data)
    shared(repo, "Query prometheus on localhost, or prometheus-operated.monitoring.svc.")
    assert "acme" in contracts.load(repo)


def test_the_value_named_never_appears_in_the_problem(repo: Path) -> None:
    shared(repo, "Key AKIAACMEACMEACMEACME was rotated.")
    assert "AKIA" not in " ".join(problems(repo))


def test_every_file_under_shared_is_checked(repo: Path) -> None:
    other = repo / "shared" / "notes" / "deep" / "x.txt"
    other.parent.mkdir(parents=True)
    other.write_text("acme")
    assert problems(repo)[0].startswith(f"{other}:1: names Contract 'acme'")


def test_the_demo_shared_knowledge_names_no_contract(two_contracts: Any) -> None:
    assert set(two_contracts) == {"demo-shop", "demo-bank"}  # load() checked it


# No write path: the tools only read, never by path, and the mounts are read-only.

PATH_LIKE = {"path", "file", "filename", "dir", "directory", "filepath"}


@pytest.mark.anyio
async def test_the_agent_has_no_tool_that_writes_files(
    two_contracts: Any, settings: Settings, fake_cluster: Any
) -> None:
    """Every tool either reads or is a Kubernetes action on the cluster; none takes a
    file path."""
    cluster_actions = {"kubernetes_evict_pod", "kubernetes_scale_deployment"}
    for c in two_contracts.values():
        actions = copy.deepcopy(c.model_dump(mode="json"))
        actions["integrations"][0]["enable_actions"] = True  # the most a Contract offers
        widest = contracts.build(actions, secrets=c._secrets, runbook_dirs=c.runbook_dirs)
        apis = {cl.name: fake_cluster for cl in widest.clusters}
        tb = agent.build_mcp(widest, settings, apis, snapshots=True)
        writes = {name for name, a in tb.access.items() if a == "write"}
        assert writes == cluster_actions, c.id
        async with Client(tb.mcp) as client:
            for tool in await client.list_tools():
                if tool.name in tb.access:
                    assert not set(tool.input_schema.get("properties", {})) & PATH_LIKE, tool.name


@pytest.mark.anyio
async def test_a_runbook_is_read_by_name_never_by_path(
    two_contracts: Any, settings: Settings, fake_cluster: Any
) -> None:
    shop = two_contracts["demo-shop"]
    tb = agent.build_mcp(shop, settings, {cl.name: fake_cluster for cl in shop.clusters})
    async with Client(tb.mcp) as client:
        for name in ("../demo-bank/runbooks/ledger-lag", "../../demo-bank/contract", "/etc/passwd"):
            with pytest.raises(ToolError, match="unknown runbook"):
                await client.call_tool("runbooks_read_runbook", {"name": name})


def test_the_hub_mounts_the_contracts_repo_read_only() -> None:
    compose = yaml.safe_load((ROOT / "deploy" / "hub" / "compose.yaml").read_text())
    hub = compose["services"]["hub"]
    assert hub["read_only"] is True
    assert "${AIOPS_CONTRACTS:-./contracts}:/contracts:ro" in hub["volumes"]
    docs = list(yaml.safe_load_all((ROOT / "deploy" / "base" / "deployment.yaml").read_text()))
    pod = next(d for d in docs if d["kind"] == "Deployment")["spec"]["template"]["spec"]
    (agent_container,) = pod["containers"]
    assert agent_container["securityContext"]["readOnlyRootFilesystem"] is True
    mounts = {m["mountPath"]: m for m in agent_container["volumeMounts"]}
    contract_mounts = [m for p, m in mounts.items() if p.startswith("/contracts")]
    assert contract_mounts and all(m.get("readOnly") for m in contract_mounts)


def test_the_terms_a_contract_masks_name_it() -> None:
    """They are its identifiers by its own account (slice 6.4)."""
    data = copy.deepcopy(FULL) | {"data_policy": {"mask": {"terms": ["globex.example"]}}}
    secrets = {k: SecretStr("x") for k in ("jira", "aws", "gcp", "mask-key")}
    found = contracts.identifiers(contracts.build(data, secrets=secrets))
    assert found["globex.example"] == "masked term"
