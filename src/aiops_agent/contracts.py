"""Contracts: one directory per Contract in the private contracts repo (ADR 0003).

    <contracts-dir>/<id>/contract.yaml       what the Contract runs; secret *names* only
    <contracts-dir>/<id>/secrets.sops.yaml   SOPS-encrypted map: secret name -> value
    <contracts-dir>/<id>/runbooks/*.md       this Contract's Runbooks
    <contracts-dir>/shared/runbooks/*.md     Shared knowledge, for every Contract

`load()` reads every Contract, decrypts its secrets with the `sops` binary and
reports every problem at once as `path: field: message`. Secret values never
appear in errors, logs or repr.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    PrivateAttr,
    SecretStr,
    Tag,
    ValidationError,
    model_validator,
)

SECRETS_FILE = "secrets.sops.yaml"
SHARED = "shared"

# Becomes a URL path segment (/contracts/{id}/...), so a lowercase slug.
Slug = Annotated[str, Field(pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", max_length=63)]


class Strict(BaseModel):
    # A typo must fail, not be ignored. Fields are added when a slice gives them behaviour.
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class Cluster(Strict):
    name: Slug
    namespaces: list[str] = Field(min_length=1)
    # Where ArgoCD Applications and Flux Kustomizations/HelmReleases live (argocd,
    # flux-system). Only recent_changes reads there, and only objects that deploy
    # into `namespaces`; no other tool may name these namespaces.
    gitops_namespaces: list[str] = []
    in_cluster: bool = False
    context: str | None = None
    kubeconfig_file: Path | None = None  # default: ~/.kube/config
    kubeconfig_secret: str | None = None
    # A kubeconfig credential plugin runs as a command on the Hub, next to every other
    # Contract's secrets. Refused unless set here, where review of the contracts repo sees it.
    allow_exec: bool = False

    @model_validator(mode="after")
    def _one_source(self) -> "Cluster":
        if (
            self.in_cluster
            + (self.kubeconfig_file is not None)
            + (self.kubeconfig_secret is not None)
            > 1
        ):
            raise ValueError("set only one of in_cluster, kubeconfig_file, kubeconfig_secret")
        if not self.in_cluster and not self.context:
            raise ValueError("context is required unless in_cluster (no silent default context)")
        return self


class Kubernetes(Strict):
    name: Literal["kubernetes"]
    enable_actions: bool = False
    max_replicas: int = Field(10, ge=1)


class Prometheus(Strict):
    name: Literal["prometheus"]
    url: str
    token_secret: str | None = None


class Jira(Strict):
    """The Contract's Jira Cloud: its past issues as Evidence, its project for new ones."""

    name: Literal["jira"]
    url: str = Field(pattern=r"^https://[^/\s]+/?$")  # Basic auth: never over plain http
    email: str  # the API token's owner
    token_secret: str
    project: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")  # every search stays inside it
    issue_type: str = "Task"  # for the Create Jira issue button: as the project names it


class Aws(Strict):
    """The Contract's AWS account, read-only: CloudWatch metrics, alarms and logs, and
    CloudTrail's management events, with an IAM user's key."""

    name: Literal["aws"]
    regions: list[Annotated[str, Field(pattern=r"^[a-z]{2}(-[a-z]+)+-[0-9]$")]] = Field(
        min_length=1
    )  # every call goes to one of these; the first is the default
    access_key_id: str = Field(pattern=r"^AKIA[A-Z0-9]{16}$")  # an IAM user's long-term key
    secret_access_key_secret: str


class Runbooks(Strict):
    name: Literal["runbooks"]  # reads <contract dir>/runbooks


class Probe(Strict):
    tool: str  # one of the vendor's tools listed `read`
    args: dict[str, Any] = {}


class Vendor(Strict):
    """A vendor MCP server, started by the Hub from its registry (servers/vendors.py).
    Its tools appear as <name>_<tool>; only those in `tools` are visible, with the
    Hub's own read or write (ADR 0002). Secrets reach it as environment variables."""

    name: Slug
    vendor: str
    env: dict[str, str] = {}
    env_secrets: dict[str, str] = {}  # variable -> secret name in secrets.sops.yaml
    tools: dict[str, Literal["read", "write"]] = Field(min_length=1)
    probe: Probe | None = None  # health; default: start it and check `tools` are offered

    @model_validator(mode="before")
    @classmethod
    def _is_vendor(cls, data: Any) -> Any:
        if isinstance(data, dict) and "vendor" not in data:
            raise ValueError(
                f"unknown integration {data.get('name')!r}: the builtins are "
                f"{', '.join(BUILTINS)}; a vendor integration needs `vendor:`"
            )
        return data

    @model_validator(mode="after")
    def _known(self) -> "Vendor":
        from aiops_agent.servers.vendors import VENDORS

        if self.vendor not in VENDORS:
            known = ", ".join(sorted(VENDORS)) or "none yet"
            raise ValueError(f"vendor {self.vendor!r} isn't in the Hub's registry ({known})")
        allowed = VENDORS[self.vendor].env
        if refused := sorted((set(self.env) | set(self.env_secrets)) - allowed):
            raise ValueError(
                f"vendor {self.vendor!r} takes only these variables: "
                f"{', '.join(sorted(allowed)) or 'none'}; refused: {', '.join(refused)}"
            )
        if plain := sorted(set(self.env) & VENDORS[self.vendor].secret_env):
            raise ValueError(
                f"{', '.join(plain)} hold credentials: set them in env_secrets "
                "(a name in secrets.sops.yaml), never in plain env"
            )
        if self.probe and self.tools.get(self.probe.tool) != "read":
            raise ValueError(f"probe tool {self.probe.tool!r} must be listed in tools as read")
        spec = VENDORS[self.vendor]
        if missing := sorted(set(spec.required_env) - set(self.env) - set(self.env_secrets)):
            raise ValueError(f"vendor {self.vendor!r} needs {', '.join(missing)}")
        for var, form in spec.required_env.items():
            if var in self.env and not re.fullmatch(form, self.env[var]):
                raise ValueError(f"{var}: {self.env[var]!r} doesn't match {form}")
        if spec.probe and not self.probe and self.tools.get(spec.probe[0]) != "read":
            raise ValueError(
                f"list {spec.probe[0]!r} in tools as read: it's the {self.vendor} health check"
            )
        return self


BUILTINS = ("kubernetes", "prometheus", "runbooks", "jira", "aws")


def _kind(value: Any) -> str:
    name = value.get("name") if isinstance(value, dict) else getattr(value, "name", None)
    return name if name in BUILTINS else "vendor"


Integration = Annotated[
    Annotated[Kubernetes, Tag("kubernetes")]
    | Annotated[Prometheus, Tag("prometheus")]
    | Annotated[Runbooks, Tag("runbooks")]
    | Annotated[Jira, Tag("jira")]
    | Annotated[Aws, Tag("aws")]
    | Annotated[Vendor, Tag("vendor")],
    Discriminator(_kind),
]


class Slack(Strict):
    # A channel ID (C0123ABCD), not a name: names can be renamed. The bot must be
    # a member. One Contract per channel, so a channel always names its Contract.
    operator_channel: str = Field(pattern=r"^[CG][A-Z0-9]{8,}$")
    # Optional: where the Operator can send Client reports (a Slack Connect channel
    # shared with the client). Never gets buttons.
    client_channel: str | None = Field(None, pattern=r"^[CG][A-Z0-9]{8,}$")

    @model_validator(mode="after")
    def _apart(self) -> "Slack":
        if self.client_channel == self.operator_channel:
            raise ValueError("client_channel must not be the operator_channel: clients see it")
        return self


class Contract(Strict):
    id: Slug
    name: str
    # SHA-256 of the bearer token this Contract's Alertmanager sends. A hash, not a
    # credential, so it lives in plain YAML (`aiops contracts new-token` makes one).
    webhook_token_sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")
    clusters: list[Cluster] = []
    integrations: list[Integration] = Field(min_length=1)
    slack: Slack | None = None  # where the Operator follows this Contract's Investigations
    # The Hub's AIOPS_MODEL unless set; through the Hub's gateway and key (same prefix).
    model: str | None = None
    monthly_budget_usd: float | None = Field(None, gt=0)  # calendar month, UTC

    _dir: Path = PrivateAttr(default=Path())
    _secrets: dict[str, SecretStr] = PrivateAttr(default_factory=dict)
    _runbook_dirs: list[Path] = PrivateAttr(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> "Contract":
        groups: dict[str, list[str]] = {
            "cluster": [c.name for c in self.clusters],
            "integration": [i.name for i in self.integrations],
        }
        for kind, names in groups.items():
            dupes = sorted({n for n in names if names.count(n) > 1})
            if dupes:
                raise ValueError(f"duplicate {kind} names: {dupes}")
        has_k8s = any(i.name == "kubernetes" for i in self.integrations)
        if has_k8s != bool(self.clusters):
            raise ValueError("the kubernetes integration and clusters go together")
        return self

    @property
    def dir(self) -> Path:
        return self._dir

    @property
    def runbook_dirs(self) -> list[Path]:
        """Shared knowledge first, then the Contract's own: its Runbook wins on a name clash."""
        return self._runbook_dirs

    def secret(self, name: str) -> SecretStr:
        return self._secrets[name]

    def has_secret(self, name: str) -> bool:
        return name in self._secrets

    def secret_refs(self) -> set[str]:
        """Every `*_secret` field and every value of a `*_secrets` map, so a new
        integration's credentials are checked without being listed here."""
        refs: set[str] = set()
        for item in (*self.clusters, *self.integrations):
            for field in type(item).model_fields:
                value = getattr(item, field)
                if field.endswith("_secret") and value is not None:
                    refs.add(value)
                elif field.endswith("_secrets"):
                    refs.update(value.values())
        return refs


class ContractError(Exception):
    """Every problem found, one `path: field: message` line each."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


def load(directory: Path) -> dict[str, Contract]:
    if not directory.is_dir():
        raise ContractError([f"{directory}: not a directory"])
    contracts: dict[str, Contract] = {}
    owners: dict[str, list[str]] = defaultdict(list)  # age recipient -> Contract ids
    problems: list[str] = []
    for path in sorted(directory.glob("*/contract.yaml")):
        try:
            contract, recipients = _load_one(path)
        except ContractError as e:
            problems += e.problems
            continue
        contracts[contract.id] = contract
        for r in recipients:
            owners[r].append(contract.id)
    by_token: dict[str, list[str]] = defaultdict(list)
    for c in contracts.values():
        if c.webhook_token_sha256:
            by_token[c.webhook_token_sha256].append(c.id)
    for ids in by_token.values():
        if len(ids) > 1:
            problems.append(
                f"{directory}: {', '.join(ids)} share a webhook token; "
                "one Contract's Alertmanager could post as another"
            )
    by_channel: dict[str, list[str]] = defaultdict(list)
    for c in contracts.values():
        if c.slack:  # operator and client channels alike: a channel names one Contract
            by_channel[c.slack.operator_channel].append(c.id)
            if c.slack.client_channel:
                by_channel[c.slack.client_channel].append(c.id)
    for channel, ids in by_channel.items():
        if len(ids) > 1:
            problems.append(
                f"{directory}: {', '.join(ids)} share Slack channel {channel}; "
                "one channel per Contract"
            )
    for recipient, ids in owners.items():
        if len(ids) > 1:
            problems.append(
                f"{directory}: {', '.join(ids)} share age recipient {recipient}; "
                "each Contract needs its own key"
            )
    if not contracts and not problems:
        problems.append(f"{directory}: no */contract.yaml found")
    if problems:
        raise ContractError(problems)
    return contracts


def _load_one(path: Path) -> tuple[Contract, set[str]]:
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise ContractError([f"{path}: invalid YAML: {e}"]) from None
    try:
        contract = Contract.model_validate(raw)
    except ValidationError as e:
        raise ContractError(_lines(str(path), e)) from None
    problems = []
    if contract.id != path.parent.name:
        problems.append(
            f"{path}: id: {contract.id!r} must match its directory {path.parent.name!r}"
        )
    if (path.parent / "secrets.yaml").exists():
        problems.append(
            f"{path.parent / 'secrets.yaml'}: plaintext secrets; encrypt as {SECRETS_FILE}"
        )
    secrets, recipients = {}, set()
    secrets_path = path.parent / SECRETS_FILE
    if secrets_path.exists():
        recipients = _recipients(secrets_path)
        secrets = _decrypt(secrets_path)
    for name in sorted(contract.secret_refs() - secrets.keys()):
        problems.append(f"{path}: secret {name!r} is not in {SECRETS_FILE}")
    for i, cluster in enumerate(contract.clusters):
        if cluster.kubeconfig_secret in secrets:
            kubeconfig = _yaml_or_none(secrets[cluster.kubeconfig_secret])
        elif cluster.kubeconfig_file and cluster.kubeconfig_file.expanduser().is_file():
            kubeconfig = read_kubeconfig(cluster.kubeconfig_file)
        else:
            continue  # the default kubeconfig is the Hub's, checked when it connects
        if kubeconfig is None:
            problems.append(f"{path}: clusters.{i}: kubeconfig is not valid YAML")
        elif refusal := refuse_plugin(cluster, kubeconfig):
            problems.append(f"{path}: clusters.{i}: {refusal}")
    if problems:
        raise ContractError(problems)
    contract._dir = path.parent
    contract._secrets = {k: SecretStr(v) for k, v in secrets.items()}
    contract._runbook_dirs = [path.parent.parent / SHARED / "runbooks", path.parent / "runbooks"]
    return contract, recipients


def _yaml_or_none(text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return None  # never echo the text: it is a credential


def read_kubeconfig(path: Path | None) -> dict[str, Any]:
    """The contexts and users the kubernetes client would see: `path`, or else
    KUBECONFIG / ~/.kube/config, merged first-wins like kubectl."""
    env = os.environ.get("KUBECONFIG", "~/.kube/config")
    paths = [path] if path else [Path(p) for p in env.split(os.pathsep) if p]
    merged: dict[str, Any] = {"contexts": [], "users": []}
    seen = set()
    for p in paths:
        p = p.expanduser()
        if not p.is_file():
            continue
        data = yaml.safe_load(p.read_text()) or {}
        for key in ("contexts", "users"):
            for entry in data.get(key) or []:
                if isinstance(entry, dict) and (key, entry.get("name")) not in seen:
                    seen.add((key, entry.get("name")))
                    merged[key].append(entry)
    return merged


def credential_plugin(kubeconfig: Any, context: str | None) -> str | None:
    """The command `context`'s user would run on the Hub to get credentials, if any:
    an exec plugin, or an auth-provider (gcp's can run a cmd-path)."""
    if not isinstance(kubeconfig, dict):
        return None

    def named(key: str, name: Any) -> dict[str, Any]:
        for entry in kubeconfig.get(key) or []:
            if isinstance(entry, dict) and entry.get("name") == name:
                inner = entry.get(key[:-1])  # contexts[].context, users[].user
                return inner if isinstance(inner, dict) else {}
        return {}

    user = named("users", named("contexts", context).get("user"))
    if "exec" in user:
        return f"exec plugin {(user['exec'] or {}).get('command')!r}"
    if "auth-provider" in user:
        return f"auth-provider {(user['auth-provider'] or {}).get('name')!r}"
    return None


def refuse_plugin(cluster: Cluster, kubeconfig: Any) -> str | None:
    """Why this cluster's kubeconfig may not be used, or None."""
    plugin = None if cluster.allow_exec else credential_plugin(kubeconfig, cluster.context)
    if plugin is None:
        return None
    return (
        f"cluster {cluster.name!r}: its kubeconfig runs {plugin} on the Hub; "
        "set allow_exec: true on the cluster to permit it"
    )


def _lines(where: str, e: ValidationError) -> list[str]:
    # loc and msg only: pydantic's `input` could echo a value.
    return [
        f"{where}: {'.'.join(map(str, err['loc'])) or '<root>'}: {err['msg']}" for err in e.errors()
    ]


def build(
    data: dict[str, Any],
    *,
    secrets: dict[str, SecretStr] | None = None,
    runbook_dirs: Sequence[Path] = (),
) -> Contract:
    """A Contract from data already in memory (tests, evals, the env settings)."""
    contract = Contract.model_validate(data)
    contract._secrets = dict(secrets or {})
    contract._runbook_dirs = list(runbook_dirs)
    return contract


def _recipients(path: Path) -> set[str]:
    """Read from the file's sops metadata: no key needed. Refuses unencrypted files."""
    try:
        meta = (yaml.safe_load(path.read_text()) or {}).get("sops")
    except (yaml.YAMLError, AttributeError):
        meta = None
    if not isinstance(meta, dict):
        raise ContractError([f"{path}: not encrypted with sops; refusing to read it"])
    return {a["recipient"] for a in meta.get("age") or [] if "recipient" in a}


def _decrypt(path: Path) -> dict[str, str]:
    sops = shutil.which("sops")
    if sops is None:
        raise ContractError([f"{path}: sops is not on PATH (brew install sops)"])
    proc = subprocess.run(  # noqa: S603 - fixed binary and arguments, no shell
        [sops, "--decrypt", "--output-type", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        reason = (proc.stderr.strip().splitlines() or ["unknown error"])[0]
        raise ContractError([f"{path}: sops could not decrypt: {reason}"])
    data: Any = json.loads(proc.stdout)
    if not isinstance(data, dict):
        raise ContractError([f"{path}: must be a map of secret name to value"])
    bad = sorted(str(k) for k, v in data.items() if not isinstance(v, str))
    if bad:
        # Name the keys, never the values.
        raise ContractError([f"{path}: {k}: value must be a string" for k in bad])
    return data


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> tuple[str, str]:
    """A fresh webhook token and the hash that goes in contract.yaml."""
    token = secrets.token_urlsafe(32)
    return token, token_hash(token)


# Compared when the Contract is unknown, so a wrong id costs the same as a wrong token.
_NO_MATCH = token_hash(secrets.token_urlsafe(32))


def token_matches(contract: Contract | None, token: str) -> bool:
    expected = (contract and contract.webhook_token_sha256) or _NO_MATCH
    return hmac.compare_digest(token_hash(token), expected)
