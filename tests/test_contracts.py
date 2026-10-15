import copy
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from aiops_agent import cli, contracts
from tests.conftest import DEMO_CONTRACTS, use_age_keys

BASE: dict[str, Any] = {
    "id": "acme",
    "name": "Acme",
    "clusters": [{"name": "prod", "context": "prod", "namespaces": ["shop"]}],
    "integrations": [{"name": "kubernetes"}],
}


def write(root: Path, data: dict[str, Any], directory: str | None = None) -> Path:
    path = root / (directory or data["id"]) / "contract.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data))
    return path


def encrypt(path: Path, secrets: dict[str, Any], contract_id: str = "demo-shop") -> None:
    """Encrypt `secrets` for one demo Contract's test key."""
    key = (DEMO_CONTRACTS / "test-keys" / f"{contract_id}.agekey").read_text()
    recipient = key.split("# public key: ")[1].split()[0]
    path.write_text(yaml.safe_dump(secrets))
    sops = shutil.which("sops")
    assert sops, "sops is required: brew install sops"
    subprocess.run([sops, "--encrypt", "--age", recipient, "--in-place", str(path)], check=True)  # noqa: S603


def problems(directory: Path) -> list[str]:
    with pytest.raises(contracts.ContractError) as e:
        contracts.load(directory)
    return e.value.problems


def test_demo_contracts_load(two_contracts: dict[str, contracts.Contract]) -> None:
    shop, bank = two_contracts["demo-shop"], two_contracts["demo-bank"]
    assert shop.secret("prometheus-token").get_secret_value() == "shop-demo-token"
    assert bank.secret("prometheus-token").get_secret_value() == "bank-demo-token"
    assert shop.dir == DEMO_CONTRACTS / "demo-shop"
    assert [c.namespaces for c in bank.clusters] == [["bank"]]
    k8s = bank.integrations[0]
    assert isinstance(k8s, contracts.Kubernetes)
    assert (k8s.enable_actions, k8s.max_replicas) == (True, 4)
    # Isolation tests need B's names to be foreign to A.
    assert not {c.name for c in shop.clusters} & {c.name for c in bank.clusters}


def test_every_secret_field_is_a_checked_ref(tmp_path: Path) -> None:
    data = copy.deepcopy(BASE)
    data["clusters"][0]["kubeconfig_secret"] = "kc"
    data["integrations"].append({"name": "prometheus", "url": "http://p", "token_secret": "tok"})
    write(tmp_path, data)
    assert problems(tmp_path) == [
        f"{tmp_path / 'acme' / 'contract.yaml'}: secret {name!r} is not in secrets.sops.yaml"
        for name in ("kc", "tok")
    ]


def test_one_contracts_key_cannot_decrypt_another(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    use_age_keys(monkeypatch, tmp_path, "demo-shop")
    found = problems(DEMO_CONTRACTS)
    assert found and all("demo-bank/secrets.sops.yaml" in p for p in found)


def test_contracts_must_not_share_an_age_key(two_contracts: Any, tmp_path: Path) -> None:
    root = tmp_path / "contracts"
    shutil.copytree(DEMO_CONTRACTS, root)
    shutil.copy(root / "demo-shop" / "secrets.sops.yaml", root / "demo-bank" / "secrets.sops.yaml")
    assert any("demo-bank, demo-shop share age recipient" in p for p in problems(root))


def change(path: str, value: Any) -> Callable[[dict[str, Any]], None]:
    """Set (or delete, when value is ...) one dotted path in a contract dict."""

    def apply(d: dict[str, Any]) -> None:
        *parents, last = path.split(".")
        node: Any = d
        for p in parents:
            node = node[int(p)] if p.isdigit() else node[p]
        if value is ...:
            del node[int(last) if last.isdigit() else last]
        else:
            node[int(last) if last.isdigit() else last] = value

    return apply


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (change("id", "other"), "id: 'other' must match its directory 'acme'"),
        (change("clusters", [*BASE["clusters"], *BASE["clusters"]]), "duplicate cluster names"),
        (
            change("integrations", [{"name": "kubernetes"}, {"name": "kubernetes"}]),
            "duplicate integration names",
        ),
        (change("clusters.0.namespaces", []), "clusters.0.namespaces: List should have at least 1"),
        (change("clusters.0.context", ...), "context is required unless in_cluster"),
        (change("clusters.0.name", "Prod_1"), "clusters.0.name: String should match"),
        (change("integration", []), "integration: Extra inputs are not permitted"),
        (change("clusters", []), "the kubernetes integration and clusters go together"),
        (change("integrations", [{"name": "runbooks"}]), "the kubernetes integration and clusters"),
        (change("integrations", [{"name": "splunk"}]), "integrations.0: Input tag 'splunk'"),
        (
            change("clusters.0.kubeconfig_secret", "prod-kubeconfig"),
            "secret 'prod-kubeconfig' is not in secrets.sops.yaml",
        ),
    ],
)
def test_invalid_contract_names_file_and_field(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None], expected: str
) -> None:
    data = copy.deepcopy(BASE)
    mutate(data)
    path = write(tmp_path, data, directory="acme")
    found = problems(tmp_path)
    assert any(p.startswith(f"{path}: ") and expected in p for p in found), found


def test_two_kubeconfig_sources_are_rejected(tmp_path: Path) -> None:
    data = copy.deepcopy(BASE)
    data["clusters"][0] |= {"kubeconfig_file": "/k.yaml", "kubeconfig_secret": "kc"}
    write(tmp_path, data)
    assert any("set only one of" in p for p in problems(tmp_path))


def test_in_cluster_needs_no_context(tmp_path: Path) -> None:
    data = copy.deepcopy(BASE)
    data["clusters"] = [{"name": "here", "in_cluster": True, "namespaces": ["shop"]}]
    write(tmp_path, data)
    assert contracts.load(tmp_path)["acme"].clusters[0].in_cluster


def test_every_contracts_problems_are_reported_together(tmp_path: Path) -> None:
    write(tmp_path, {**BASE, "id": "one", "clusters": []})
    write(tmp_path, {**BASE, "id": "two", "name": None})
    found = problems(tmp_path)
    assert any("one/contract.yaml" in p for p in found)
    assert any("two/contract.yaml" in p for p in found)


@pytest.mark.parametrize("name", ["secrets.sops.yaml", "secrets.yaml"])
def test_plaintext_secrets_are_refused(tmp_path: Path, name: str) -> None:
    write(tmp_path, BASE)
    (tmp_path / "acme" / name).write_text("token: plain-value\n")
    found = problems(tmp_path)
    assert any(name in p and ("not encrypted" in p or "plaintext" in p) for p in found), found
    assert "plain-value" not in "\n".join(found)


def test_secret_values_never_reach_errors_or_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    use_age_keys(monkeypatch, tmp_path, "demo-shop", "demo-bank")
    root = tmp_path / "contracts"
    data = copy.deepcopy(BASE)
    data["clusters"][0]["kubeconfig_secret"] = "kubeconfig"
    write(root, data)
    # A kubeconfig pasted as a YAML map instead of a string.
    encrypt(root / "acme" / "secrets.sops.yaml", {"kubeconfig": {"token": "TOPSECRET-1"}})
    assert cli.main(["contracts", "validate", str(root)]) == 1
    out = capsys.readouterr()
    assert "kubeconfig: value must be a string" in out.err
    assert "TOPSECRET" not in out.out + out.err

    assert cli.main(["contracts", "validate", str(DEMO_CONTRACTS)]) == 0
    out = capsys.readouterr()
    assert "demo-shop: clusters kind" in out.out
    assert "demo-token" not in out.out + out.err
    shop = contracts.load(DEMO_CONTRACTS)["demo-shop"]
    assert "demo-token" not in repr(shop) + str(shop) + shop.model_dump_json()


def test_missing_sops_is_explained(two_contracts: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(contracts.shutil, "which", lambda _: None)
    assert any("sops is not on PATH" in p for p in problems(DEMO_CONTRACTS))


def test_empty_or_missing_directory(tmp_path: Path) -> None:
    assert problems(tmp_path) == [f"{tmp_path}: no */contract.yaml found"]
    assert problems(tmp_path / "nope") == [f"{tmp_path / 'nope'}: not a directory"]
