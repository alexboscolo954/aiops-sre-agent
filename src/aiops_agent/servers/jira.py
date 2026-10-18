"""Jira MCP server: the Contract's past issues as Evidence, read-only (slice 4.4).

Jira Cloud's REST API v3 with the Contract's own email and API token. The server
writes every JQL query itself, inside the Contract's project; the model passes only
words, so it can't widen a search to another project the token can see. Issue text
is Atlassian's document format, flattened and capped.
"""

import re
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import SecretStr

from aiops_agent.safety import truncate
from aiops_agent.servers import Access

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
ACCESS: dict[str, Access] = {"search_issues": "read", "get_issue": "read"}  # ADR 0002
FIELDS = ["summary", "status", "resolution", "created", "resolutiondate", "labels"]
DESCRIPTION_LIMIT = 4000
COMMENT_LIMIT = 1500
GUIDE = """\
Past issues (jira_ tools): search the Contract's Jira for the failing service or the
error (jira_search_issues). An earlier issue with the same cause, and how it was
resolved (jira_get_issue), is strong evidence and a likely fix; cite its key.
"""


def words(text: str) -> str:
    """Only word characters reach the JQL: no quote, operator or wildcard, and
    `fraud-check.risk` searches for fraud, check and risk."""
    return " ".join(re.findall(r"\w+", text))[:200]


def adf_text(node: Any) -> str:
    """Atlassian document format to plain text: each block on its own line."""
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return str(node.get("text", ""))
    inner = "".join(adf_text(child) for child in node.get("content", []))
    block = node.get("type") in {"paragraph", "heading", "codeBlock", "listItem", "blockquote"}
    return inner + "\n" if block else inner


def build_server(
    url: str, email: str, token: SecretStr, project: str, http: httpx.Client | None = None
) -> FastMCP:
    base = url.rstrip("/")
    if http is None:
        auth = (email, token.get_secret_value())
        http = httpx.Client(
            base_url=base, auth=auth, timeout=15, headers={"Accept": "application/json"}
        )
    mcp = FastMCP("jira", instructions="Search the Contract's past Jira issues.")

    def api(method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = http.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            raise ToolError(f"Jira unreachable: {type(e).__name__}") from None
        if resp.status_code != 200:
            try:
                why = "; ".join(resp.json().get("errorMessages", [])) or resp.reason_phrase
            except ValueError:
                why = resp.reason_phrase
            raise ToolError(f"Jira error {resp.status_code}: {why}")
        return resp.json()

    def summary(issue: dict[str, Any]) -> dict[str, Any]:
        f = issue.get("fields") or {}
        return {
            "key": issue["key"],
            "summary": f.get("summary"),
            "status": (f.get("status") or {}).get("name"),
            "resolution": (f.get("resolution") or {}).get("name"),
            "created": f.get("created"),
            "resolved": f.get("resolutiondate"),
            "labels": f.get("labels") or [],
            "url": f"{base}/browse/{issue['key']}",
        }

    @mcp.tool(annotations=READ)
    def search_issues(text: str, days: int = 365, limit: int = 10) -> list[dict[str, Any]]:
        """Issues in this Contract's Jira project that mention the words of `text` (a
        service, an error message), created in the last `days`, newest first."""
        terms = words(text)
        if not terms:
            raise ToolError("give some words to search for")
        days, limit = max(1, min(days, 3650)), max(1, min(limit, 25))
        jql = (
            f'project = "{project}" AND text ~ "{terms}" '
            f"AND created >= -{days}d ORDER BY created DESC"
        )
        body = {"jql": jql, "maxResults": limit, "fields": FIELDS}
        data = api("POST", "/rest/api/3/search/jql", json=body)
        return [summary(i) for i in data.get("issues", [])]

    @mcp.tool(annotations=READ)
    def get_issue(key: str) -> dict[str, Any]:
        """One issue of this Contract's project (e.g. OPS-123): its description, how it
        was resolved, and its latest comments."""
        if not re.fullmatch(r"[A-Z][A-Z0-9_]+-[0-9]+", key):
            raise ToolError(f"not an issue key: {key[:40]!r}")
        fields = ",".join([*FIELDS, "project", "description", "comment"])
        issue = api("GET", f"/rest/api/3/issue/{key}", params={"fields": fields})
        f = issue.get("fields") or {}
        # Checked on the issue that came back: a moved issue still answers its old key.
        if (f.get("project") or {}).get("key") != project:
            raise ToolError(f"{key} is not in this Contract's Jira project")
        comments = (f.get("comment") or {}).get("comments", [])[-5:]
        return {
            **summary(issue),
            "description": truncate(adf_text(f.get("description")).strip(), DESCRIPTION_LIMIT),
            "comments": [
                {
                    "author": (c.get("author") or {}).get("displayName"),
                    "created": c.get("created"),
                    "body": truncate(adf_text(c.get("body")).strip(), COMMENT_LIMIT),
                }
                for c in comments
            ],
        }

    return mcp
