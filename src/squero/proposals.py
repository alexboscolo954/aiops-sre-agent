"""Proposed changes (slice 11.3): a pull request on the contracts repo that edits one
Contract's Sizing policy, opened from the Hub MCP server for the Operator to merge.

GitHub Free enforces no branch protection on a private repo, so nothing there stops
the token from writing `main`: this module never does. It creates an `squero/` branch,
commits the edited contract.yaml there and opens the pull request; reading main's ref
is how it checks that GitHub has the commit the Hub loaded, and the file's blob that it
has the file the Hub loaded (a clone with local edits differs from both).

The edit is made with ruamel.yaml so comments and layout survive, then the new text is
read the way the Hub reads it (PyYAML) and validated: everything but `sizing` must be
unchanged, and the Contract must still build. All of that before the first write.
"""

import asyncio
import base64
import hashlib
from io import StringIO
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from squero import contracts, listprices, masking
from squero.contracts import Contract

API = "https://api.github.com"
BASE = "main"
BRANCHES = "squero/"
MATCH = ("cluster", "namespace", "kind", "name", "container")


class Refused(Exception):
    """Why a change was not proposed, in words for the Operator."""


class _Edit(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Match(_Edit):
    cluster: str | None = None
    namespace: str | None = None  # a glob
    kind: str | None = None
    name: str | None = None  # a glob
    container: str | None = None

    def match(self) -> dict[str, str]:
        return {k: v for k in MATCH if (v := getattr(self, k)) is not None}


class SetRule(_Match):
    """The rule with exactly this match gets `policy`; without one, a new rule goes
    first (the first match wins). automate (slice 12.6a): true turns Automation on for
    it, false off, None keeps what the rule has."""

    edit: Literal["set_rule"]
    policy: str
    automate: bool | None = None


class RemoveRule(_Match):
    """The rule with exactly this match goes."""

    edit: Literal["remove_rule"]


class SetDefault(_Edit):
    edit: Literal["set_default"]
    policy: str


class SetPolicy(_Edit):
    """One of the Contract's own policies, created or replaced: a built-in with the
    settings named here changed (as `contract.yaml` writes it: 7d, 0.15, 256Mi)."""

    edit: Literal["set_policy"]
    name: str
    base: Literal["production", "high-availability", "batch"]
    window: str | None = None
    half_life: str | None = None
    history: str | None = None
    threshold: float | None = None
    cpu: dict[Literal["percentile", "headroom", "floor", "max"], float | str] | None = None
    memory: dict[Literal["headroom", "floor", "max"], float | str] | None = None


Edit = Annotated[SetRule | RemoveRule | SetDefault | SetPolicy, Field(discriminator="edit")]


def head(clone: Path) -> str | None:
    """The commit a clone's HEAD names (a branch's loose ref or its line in packed-refs,
    or a detached HEAD's sha); None when it isn't a git clone."""
    git = clone / ".git"
    try:
        text = (git / "HEAD").read_text().strip()
    except OSError:
        return None
    if not text.startswith("ref: "):
        return text
    ref = text.removeprefix("ref: ")
    try:
        return (git / ref).read_text().strip()
    except OSError:
        pass
    try:
        packed = (git / "packed-refs").read_text()
    except OSError:
        return None
    for line in packed.splitlines():
        sha, _, name = line.partition(" ")
        if name == ref:
            return sha
    return None


def blob(data: bytes) -> str:
    """git's id for a file's content, as GitHub's contents API gives it."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()  # noqa: S324 - git's id


def _rt() -> YAML:
    rt = YAML()
    rt.preserve_quotes = True
    rt.width = 4096  # never re-wrap a long line the Operator didn't touch
    # ponytail: one layout (contract.yaml's: lists indented under their key); a file
    # written another way is re-indented, which the meaning check below still guards
    rt.indent(mapping=2, sequence=4, offset=2)
    return rt


def _flow(values: dict[str, Any]) -> CommentedMap:
    out = CommentedMap(values)
    out.fa.set_flow_style()
    return out


def apply(text: str, edits: list[Edit]) -> str:
    """contract.yaml's text with the edits made in order, comments kept."""
    rt = _rt()
    doc = rt.load(text)
    if not isinstance(doc, CommentedMap):
        raise Refused("contract.yaml is not a mapping")
    sizing = doc.setdefault("sizing", CommentedMap())
    for e in edits:
        if isinstance(e, SetDefault):
            sizing["default"] = e.policy
        elif isinstance(e, SetPolicy):
            settings = e.model_dump(exclude={"edit", "name"}, exclude_none=True)
            for res in ("cpu", "memory"):
                if res in settings:
                    settings[res] = _flow(settings[res])
            sizing.setdefault("policies", CommentedMap())[e.name] = CommentedMap(settings)
        else:
            rules = sizing.setdefault("rules", CommentedSeq())
            same = [i for i, r in enumerate(rules) if _match_of(r) == e.match()]
            if isinstance(e, RemoveRule):
                if not same:
                    raise Refused(f"no rule matches exactly {e.match()}")
                del rules[same[0]]
            elif same:
                rules[same[0]]["policy"] = e.policy
                if e.automate:
                    rules[same[0]]["automate"] = True
                elif e.automate is False:
                    rules[same[0]].pop("automate", None)
            else:
                on = {"automate": True} if e.automate else {}
                rules.insert(0, _flow({**e.match(), "policy": e.policy, **on}))
    out = StringIO()
    rt.dump(doc, out)
    return out.getvalue()


def _match_of(rule: Any) -> dict[str, str]:
    return {k: rule[k] for k in MATCH if isinstance(rule, dict) and k in rule}


def check(c: Contract, old: str, new: str) -> None:
    """The new text as the Hub will read it: only `sizing` changed, and still a valid
    Contract."""
    before, after = yaml.safe_load(old), yaml.safe_load(new)
    if not isinstance(after, dict):
        raise Refused("the edit left contract.yaml without a mapping")
    if {k: v for k, v in before.items() if k != "sizing"} != {
        k: v for k, v in after.items() if k != "sizing"
    }:
        raise Refused("the edit changed more than the Sizing policy")
    if before.get("sizing") == after.get("sizing"):
        raise Refused("the edits change nothing")
    try:
        contracts.build(after, secrets=dict(c._secrets))
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
        raise Refused(f"the Contract would not load: {problems}") from None


def placeholders(edits: list[Edit]) -> None:
    """A placeholder still in an edit was never handed out (or the Hub restarted since):
    it would become a rule that matches nothing."""
    for e in edits:
        text = e.model_dump_json()
        if found := masking.PLACEHOLDER.search(text):
            raise Refused(f"{found[0]} was not handed out by this Hub: list again and use it")


def _describe(e: Edit) -> str:
    if isinstance(e, SetDefault):
        return f"default policy: {e.policy}"
    if isinstance(e, SetPolicy):
        return f"policy {e.name}: {e.model_dump(exclude={'edit', 'name'}, exclude_none=True)}"
    match = ", ".join(f"{k} {v}" for k, v in e.match().items())
    if not isinstance(e, SetRule):
        return f"rule {match}: removed"
    turned = {True: ", Automation on", False: ", Automation off", None: ""}[e.automate]
    return f"rule {match}: {e.policy}{turned}"


def open_pull_request(
    http: httpx.Client,
    repo: str,
    token: str,
    loaded: str | None,
    c: Contract,
    loaded_blob: str | None,
    edits: list[Edit],
    title: str,
    why: str,
    by: str,
    branch: str,
) -> str:
    """The pull request's URL. Every read and the validation come before the first
    write, and every write names `branch` (an `squero/` one), never `main`."""
    path = f"{c.id}/contract.yaml"
    if loaded is None:
        raise Refused("the Hub did not load its Contracts from a git clone")
    if loaded_blob is None:
        raise Refused(f"the Hub did not load {path} from its clone")
    if not branch.startswith(BRANCHES):  # not an assert: `python -O` would drop it
        raise Refused(f"refusing to write {branch!r}: only {BRANCHES} branches")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    def call(method: str, url: str, **kw: Any) -> Any:
        r = http.request(method, f"{API}/repos/{repo}{url}", headers=headers, **kw)
        r.raise_for_status()
        return r.json()

    main = call("GET", f"/git/ref/heads/{BASE}")["object"]["sha"]
    if main != loaded:
        raise Refused(
            f"GitHub's {BASE} is at {main[:7]} but the Hub loaded {loaded[:7]}: "
            "pull the contracts repo and restart the Hub first"
        )
    file = call("GET", f"/contents/{path}", params={"ref": main})
    if file["sha"] != loaded_blob:
        raise Refused(f"{path} on GitHub is not the file the Hub loaded (a local edit?)")
    old = base64.b64decode(file["content"]).decode()
    new = apply(old, edits)
    check(c, old, new)
    call("POST", "/git/refs", json={"ref": f"refs/heads/{branch}", "sha": main})
    # ponytail: a failure after this leaves the branch behind; delete it by hand
    call(
        "PUT",
        f"/contents/{path}",
        json={
            "message": title,
            "content": base64.b64encode(new.encode()).decode(),
            "sha": file["sha"],
            "branch": branch,
        },
    )
    lines = "\n".join(f"- {_describe(e)}" for e in edits)
    body = f"{why}\n\n{lines}\n\nProposed through the Hub MCP server by {by}."
    pr = call("POST", "/pulls", json={"title": title, "head": branch, "base": BASE, "body": body})
    url: str = pr["html_url"]
    return url


async def propose(
    http: httpx.Client,
    repo: str,
    token: str,
    loaded: tuple[str | None, dict[str, str]],
    c: Contract,
    edits: list[Edit],
    title: str,
    why: str,
    by: str,
    branch: str,
) -> str:
    """open_pull_request off the event loop; any failure as Refused, an HTTP one by its
    status and host only (its text could name the URL)."""
    placeholders(edits)
    commit, blobs = loaded
    args = (http, repo, token, commit, c, blobs.get(c.id), edits, title, why, by, branch)
    try:
        return await asyncio.to_thread(open_pull_request, *args)
    except Refused:
        raise
    except Exception as e:
        raise Refused(listprices.why(e, token)) from None


def snapshot(clone: Path, by_id: dict[str, Contract]) -> tuple[str | None, dict[str, str]]:
    """At the Hub's start: the commit it loaded and each contract.yaml's blob, so a
    later `git pull` without a restart is caught."""
    files = {cid: clone / cid / "contract.yaml" for cid in by_id}  # its path in the repo
    return head(clone), {cid: blob(f.read_bytes()) for cid, f in files.items() if f.is_file()}
