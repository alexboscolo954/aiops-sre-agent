"""Each Investigation is one thread in its Contract's Slack channel: a parent message
whose status line is kept current, and a reply for each pause, Report or failure.

Web API over httpx (chat.postMessage, chat.update) with the Hub's bot token.
Socket Mode, for buttons and mentions, comes in slice 1.2. Slack is best effort:
a failed post is logged and never fails an Investigation.
"""

import asyncio
import logging
from typing import Any

import httpx
from pydantic import SecretStr

from aiops_agent.models import Investigation
from aiops_agent.safety import redact_capped

log = logging.getLogger("aiops.slack")
API = "https://slack.com/api/"
TEXT_LIMIT = 12_000  # Slack takes 40,000; long replies are unreadable anyway
RETRY_AFTER_CAP = 10.0  # ponytail: one retry after a 429, waiting at most this long
STATUS = {
    "running": ":mag: investigating",
    "awaiting_approval": ":raised_hand: waiting for your approval",
    "done": ":white_check_mark: done",
    "failed": ":x: failed",
}


def clean(text: str, limit: int = TEXT_LIMIT) -> str:
    """Escape Slack markup, then redact and cap. Alert titles and Reports come from
    clients and from tool output: `<!channel>` or `<@U…>` must arrive as text."""
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return redact_capped(escaped, limit)


def parent_text(t: Investigation) -> str:
    return f"*[{clean(t.contract_id)}] {clean(t.title, 300)}*\n{STATUS[t.status]} · `{t.id}`"


def reply_text(t: Investigation) -> str | None:
    if t.status == "awaiting_approval":
        actions = "\n".join(f"• {clean(p['description'], 2000)}" for p in t.pending)
        decide = f"Decide with `POST /investigations/{t.id}/decision`."
        return f"Waiting for your approval:\n{actions}\n{decide}"
    if t.status == "done" and t.report:
        body = t.report.to_markdown(t.executed_actions).replace("**", "*").replace("## ", "*")
        return clean(body)
    if t.status == "failed":
        return f"Investigation failed: {clean(t.error or 'unknown error', 2000)}"
    return None


class Slack:
    def __init__(self, token: SecretStr | None, http: httpx.AsyncClient) -> None:
        self.token, self.http = token, http

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        assert self.token is not None
        headers = {"Authorization": f"Bearer {self.token.get_secret_value()}"}
        for attempt in (1, 2):
            try:
                r = await self.http.post(API + method, json=payload, headers=headers, timeout=10)
            except httpx.HTTPError as e:
                log.warning("slack %s to %s: %s", method, payload["channel"], type(e).__name__)
                return None
            if r.status_code == 429 and attempt == 1:
                wait = min(float(r.headers.get("Retry-After", "1")), RETRY_AFTER_CAP)
                await asyncio.sleep(wait)
                continue
            # Slack answers HTTP 200 with {"ok": false, "error": ...}: check `ok`.
            body: dict[str, Any] = (
                r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            )
            if not body.get("ok"):
                error = body.get("error") or f"HTTP {r.status_code}"
                log.warning("slack %s to %s failed: %s", method, payload["channel"], error)
                return None
            return body
        return None

    async def post(self, channel: str, text: str, thread_ts: str | None = None) -> str | None:
        """The message's ts, or None when it wasn't posted."""
        payload = {"channel": channel, "text": text, "unfurl_links": False}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        body = await self._call("chat.postMessage", payload)
        return str(body["ts"]) if body else None

    async def update(self, channel: str, ts: str, text: str) -> None:
        await self._call("chat.update", {"channel": channel, "ts": ts, "text": text})
