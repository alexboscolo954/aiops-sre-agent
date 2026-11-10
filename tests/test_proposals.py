"""Proposed changes (slice 11.3): the edits on contract.yaml with its comments kept,
the checks before anything is written, and the pull request on GitHub that never
writes `main`."""

import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from pydantic import TypeAdapter

from squero import proposals
from squero.proposals import Refused, apply, blob, check, head
from tests.conftest import make_contract

TEXT = """\
id: acme
name: acme
clusters:
  - {name: test, context: test, namespaces: [shop, cart, payments, checkout, search, ads, mail, recommendation]}
data_policy: {mask: {terms: [acme], emails: true, ips: true}}  # a comment after a flow mapping
integrations:
  - name: kubernetes
# Sizing policies
sizing:
  policies:
    lean:  # every MiB counts
      base: production
      cpu: {headroom: 0.10}
  rules:  # the first match wins
    - {namespace: shop, name: db, policy: high-availability}
    - {namespace: shop, kind: DaemonSet, policy: lean}
"""  # noqa: E501 - a line longer than ruamel's default width, on purpose
EDITS = TypeAdapter(list[proposals.Edit])
TOKEN = "github_pat_" + "s" * 40
MAIN = "a" * 40
CONTRACT = make_contract()


def edits(*raw: dict[str, Any]) -> list[proposals.Edit]:
    return EDITS.validate_python(list(raw))


def sizing(text: str) -> Any:
    return yaml.safe_load(text)["sizing"]


# --- the clone ---------------------------------------------------------------------------


def test_head_reads_a_loose_ref_packed_refs_or_a_detached_head(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    assert head(tmp_path) is None  # not a clone
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    assert head(tmp_path) is None  # no such ref yet
    (git / "packed-refs").write_text(
        f"# pack-refs\n{'b' * 40} refs/heads/other\n{MAIN} refs/heads/main\n"
    )
    assert head(tmp_path) == MAIN
    (git / "refs" / "heads" / "main").write_text("c" * 40 + "\n")  # a loose ref wins
    assert head(tmp_path) == "c" * 40
    (git / "HEAD").write_text("d" * 40 + "\n")
    assert head(tmp_path) == "d" * 40


def test_blob_is_gits_id_for_the_content() -> None:
    assert blob(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"  # git hash-object


def test_a_snapshot_takes_each_contracts_file_at_its_path_in_the_repo(tmp_path: Path) -> None:
    (tmp_path / "acme").mkdir()
    (tmp_path / "acme" / "contract.yaml").write_text(TEXT)
    acme, bank = make_contract(), make_contract(contract_id="bank")
    assert proposals.snapshot(tmp_path, {"acme": acme, "bank": bank}) == (
        None,
        {"acme": blob(TEXT.encode())},
    )


# --- the edits ---------------------------------------------------------------------------


def test_a_rule_with_the_same_match_changes_policy_and_comments_survive() -> None:
    new = apply(
        TEXT, edits({"edit": "set_rule", "namespace": "shop", "name": "db", "policy": "lean"})
    )
    assert sizing(new)["rules"][0] == {"namespace": "shop", "name": "db", "policy": "lean"}
    assert len(sizing(new)["rules"]) == 2
    assert "# every MiB counts" in new and "# the first match wins" in new
    assert "# Sizing policies" in new


def test_every_line_outside_sizing_stays_byte_for_byte() -> None:
    new = apply(TEXT, edits({"edit": "set_default", "policy": "batch"}))
    before = TEXT.split("sizing:")[0]
    assert new.startswith(before)
    assert max(len(line) for line in before.splitlines()) > 100  # longer than ruamel's 80


def test_a_new_rule_goes_first_and_reads_like_the_others() -> None:
    new = apply(
        TEXT, edits({"edit": "set_rule", "namespace": "shop", "name": "api", "policy": "off"})
    )
    assert sizing(new)["rules"][0] == {"namespace": "shop", "name": "api", "policy": False}  # off
    assert "    - {namespace: shop, name: api, policy: off}\n" in new
    check(CONTRACT, TEXT, new)  # `off` reads back as the policy off


def test_a_rule_is_removed_by_its_exact_match_only() -> None:
    gone = apply(TEXT, edits({"edit": "remove_rule", "namespace": "shop", "name": "db"}))
    assert [r.get("name") for r in sizing(gone)["rules"]] == [None]
    with pytest.raises(Refused, match="no rule matches exactly"):
        apply(TEXT, edits({"edit": "remove_rule", "name": "db"}))  # not its whole match


def test_the_default_and_a_policy_are_set() -> None:
    new = apply(
        TEXT,
        edits(
            {"edit": "set_default", "policy": "high-availability"},
            {
                "edit": "set_policy",
                "name": "tight",
                "base": "batch",
                "window": "7d",
                "memory": {"headroom": 0.1, "max": "256Mi"},
            },
        ),
    )
    s = sizing(new)
    assert s["default"] == "high-availability"
    assert s["policies"]["tight"] == {
        "base": "batch",
        "window": "7d",
        "memory": {"headroom": 0.1, "max": "256Mi"},
    }
    assert s["policies"]["lean"] == {"base": "production", "cpu": {"headroom": 0.1}}
    check(CONTRACT, TEXT, new)


def test_a_contract_without_sizing_gets_one() -> None:
    bare = TEXT.split("# Sizing policies")[0]
    new = apply(bare, edits({"edit": "set_default", "policy": "batch"}))
    assert sizing(new) == {"default": "batch"}


def test_the_check_refuses_another_key_no_change_and_a_contract_that_would_not_load() -> None:
    with pytest.raises(Refused, match="more than the Sizing policy"):
        check(CONTRACT, TEXT, TEXT.replace("name: acme", "name: other"))
    with pytest.raises(Refused, match="change nothing"):
        check(
            CONTRACT,
            TEXT,
            apply(
                TEXT,
                edits(
                    {
                        "edit": "set_rule",
                        "namespace": "shop",
                        "name": "db",
                        "policy": "high-availability",
                    }
                ),
            ),
        )
    unknown = apply(TEXT, edits({"edit": "set_default", "policy": "nope"}))
    with pytest.raises(Refused, match=r"would not load: sizing: .*unknown policy 'nope'"):
        check(CONTRACT, TEXT, unknown)


def test_a_placeholder_never_handed_out_is_refused() -> None:
    with pytest.raises(Refused, match="<name-0a1b2c3d> was not handed out"):
        proposals.placeholders(
            edits({"edit": "set_rule", "namespace": "<name-0a1b2c3d>", "policy": "off"})
        )
    proposals.placeholders(edits({"edit": "set_rule", "namespace": "shop", "policy": "off"}))


def test_an_unknown_edit_or_field_is_refused_by_its_type() -> None:
    with pytest.raises(ValueError):
        edits({"edit": "set_limits", "policy": "off"})
    with pytest.raises(ValueError):
        edits({"edit": "set_rule", "policy": "off", "image": "evil"})


# --- the pull request --------------------------------------------------------------------


class GitHub:
    """GitHub's REST API for one repo with `files` (path -> text) on main at MAIN."""

    def __init__(self, files: dict[str, str], main: str = MAIN, fail: int | None = None):
        self.files, self.main, self.fail = files, main, fail
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            return httpx.Response(self.fail, json={"message": f"Bad credentials {TOKEN}"})
        path = request.url.path.removeprefix("/repos/me/contracts")
        if request.method == "GET" and path == "/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": self.main}})
        if request.method == "GET" and path.startswith("/contents/"):
            text = self.files[path.removeprefix("/contents/")]
            content = base64.b64encode(text.encode()).decode()
            return httpx.Response(200, json={"sha": blob(text.encode()), "content": content})
        if request.method in ("POST", "PUT"):
            return httpx.Response(201, json={"html_url": "https://github.com/me/contracts/pull/7"})
        return httpx.Response(404)

    def writes(self) -> list[tuple[str, str, dict[str, Any]]]:
        return [
            (r.method, r.url.path, json.loads(r.content))
            for r in self.requests
            if r.method != "GET"
        ]


def opened(
    gh: GitHub,
    *raw: dict[str, Any],
    loaded: str | None = MAIN,
    text: str | None = TEXT,
    branch: str = "squero/acme-20260101-000000",
) -> str:
    with httpx.Client(transport=httpx.MockTransport(gh)) as http:
        return proposals.open_pull_request(
            http,
            "me/contracts",
            TOKEN,
            loaded,
            CONTRACT,
            None if text is None else blob(text.encode()),
            edits(*raw) if raw else edits({"edit": "set_default", "policy": "batch"}),
            "Batch by default",
            "The lab runs batch jobs.",
            "mcp:op@example.com",
            branch,
        )


def test_a_pull_request_is_opened_from_its_own_branch_never_writing_main() -> None:
    gh = GitHub({"acme/contract.yaml": TEXT, "bank/contract.yaml": "id: bank\n"})
    url = opened(gh)
    assert url == "https://github.com/me/contracts/pull/7"
    branch = "squero/acme-20260101-000000"
    (ref, put, pull) = gh.writes()
    assert ref == (
        "POST",
        "/repos/me/contracts/git/refs",
        {"ref": f"refs/heads/{branch}", "sha": MAIN},
    )
    assert put[:2] == ("PUT", "/repos/me/contracts/contents/acme/contract.yaml")
    assert put[2]["branch"] == branch and put[2]["sha"] == blob(TEXT.encode())
    assert sizing(base64.b64decode(put[2]["content"]).decode())["default"] == "batch"
    assert pull[2] == {
        "title": "Batch by default",
        "head": branch,
        "base": "main",
        "body": "The lab runs batch jobs.\n\n- default policy: batch\n\n"
        "Proposed through the Hub MCP server by mcp:op@example.com.",
    }
    # the contents were read at the commit the Hub loaded, and only acme's
    reads = [r for r in gh.requests if r.method == "GET"]
    assert reads[1].url.params["ref"] == MAIN
    assert not [r for r in gh.requests if "bank" in str(r.url)]
    # the token goes to GitHub's API in its header, and nowhere else
    for r in gh.requests:
        assert r.url.host == "api.github.com"
        assert r.headers["authorization"] == f"Bearer {TOKEN}"
        assert TOKEN not in str(r.url) and TOKEN.encode() not in r.content


@pytest.mark.parametrize(
    ("gh", "loaded", "text", "why"),
    [
        (
            GitHub({"acme/contract.yaml": TEXT}, main="f" * 40),
            MAIN,
            TEXT,
            "GitHub's main is at fffffff but the Hub loaded aaaaaaa",
        ),
        (
            GitHub({"acme/contract.yaml": TEXT}),
            MAIN,
            TEXT + "# a local edit\n",
            "not the file the Hub loaded",
        ),
        (
            GitHub({"acme/contract.yaml": TEXT}),
            None,
            TEXT,
            "did not load its Contracts from a git clone",
        ),
        (
            GitHub({"acme/contract.yaml": TEXT}),
            MAIN,
            None,
            "did not load acme/contract.yaml from its clone",
        ),
    ],
)
def test_nothing_is_written_when_github_is_not_what_the_hub_loaded(
    gh: GitHub, loaded: str | None, text: str | None, why: str
) -> None:
    with pytest.raises(Refused, match=why):
        opened(gh, loaded=loaded, text=text)
    assert gh.writes() == []


def test_nothing_is_written_for_an_edit_that_would_not_load() -> None:
    gh = GitHub({"acme/contract.yaml": TEXT})
    with pytest.raises(Refused, match="would not load"):
        opened(gh, {"edit": "set_default", "policy": "nope"})
    assert gh.writes() == []


@pytest.mark.parametrize("branch", ["main", "squero-main", "refs/heads/main"])
def test_only_an_squero_branch_is_ever_written(branch: str) -> None:
    gh = GitHub({"acme/contract.yaml": TEXT})
    with pytest.raises(Refused, match="only squero/ branches"):
        opened(gh, branch=branch)
    assert gh.requests == []


@pytest.mark.anyio
async def test_an_http_failure_says_its_status_and_host_and_never_the_token() -> None:
    gh = GitHub({}, fail=401)
    with httpx.Client(transport=httpx.MockTransport(gh)) as http, pytest.raises(Refused) as e:
        await proposals.propose(
            http,
            "me/contracts",
            TOKEN,
            (MAIN, {"acme": blob(TEXT.encode())}),
            CONTRACT,
            edits({"edit": "set_default", "policy": "batch"}),
            "t",
            "",
            "mcp:op",
            "squero/acme-x",
        )
    assert str(e.value) == "HTTP 401 from api.github.com"


def test_a_rule_turns_automation_on_or_off_or_keeps_it() -> None:
    """slice 12.6a: automate true sets it, false removes it, left out keeps it."""
    rule = {"edit": "set_rule", "namespace": "shop", "name": "db", "policy": "lean"}
    on = apply(TEXT, edits({**rule, "automate": True}))
    assert sizing(on)["rules"][0] == {
        "namespace": "shop", "name": "db", "policy": "lean", "automate": True
    }  # fmt: skip
    kept = apply(on, edits({**rule, "policy": "batch"}))
    assert sizing(kept)["rules"][0]["automate"] is True
    off = apply(on, edits({**rule, "automate": False}))
    assert "automate" not in sizing(off)["rules"][0]
    new = apply(TEXT, edits({**rule, "name": "api", "automate": True}))
    assert sizing(new)["rules"][0] == {
        "namespace": "shop", "name": "api", "policy": "lean", "automate": True
    }  # fmt: skip
    assert "automate" not in sizing(apply(TEXT, edits({**rule, "name": "web"})))["rules"][0]
    assert proposals._describe(edits({**rule, "automate": True})[0]) == (
        "rule namespace shop, name db: lean, Automation on"
    )
    assert proposals._describe(edits({**rule, "automate": False})[0]).endswith("Automation off")
