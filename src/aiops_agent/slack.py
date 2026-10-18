"""Each Investigation is one thread in its Contract's Slack channel: a parent message
whose status line is kept current, and a reply for each pause, Report or failure.

Web API over httpx with the Hub's bot token. Approve and reject buttons sit on the
parent while it waits; clicks arrive over Socket Mode (the app token), so Slack
needs no public endpoint. Slack is best effort: a failed post is logged and never
fails an Investigation.
"""

import asyncio
import json
import logging
import re
from collections.abc import Callable
from typing import Any

import httpx
import websockets
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


def mrkdwn(markdown: str) -> str:
    """The Report's markdown as Slack mrkdwn: headings and **bold** become *bold*,
    and list dashes become bullets."""
    text = re.sub(r"(?m)^#{1,6}\s+(.+)$", r"*\1*", markdown)
    return re.sub(r"(?m)^- ", "• ", text.replace("**", "*"))


def parent_text(t: Investigation) -> str:
    sent = " · :outbox_tray: sent to the client" if t.client_sent_at else ""
    filed = f" · :ticket: {clean(t.jira_issue, 40)}" if t.jira_issue else ""
    return (
        f"*[{clean(t.contract_id)}] {clean(t.title, 300)}*\n"
        f"{STATUS[t.status]} · `{t.id}`{sent}{filed}"
    )


def client_text(t: Investigation) -> str:
    """The Client report: no Evidence, Executed actions, Runbook, ids or controls.
    The model's own prose can still name pods or quote a log line."""
    assert t.report is not None
    r = t.report
    md = "\n".join(
        [
            f"## {t.title}: {r.summary}",
            "",
            f"**Root cause** ({r.confidence} confidence): {r.probable_root_cause}",
            f"**Severity:** {r.severity}  ·  **Affected:** {', '.join(r.affected) or '-'}",
            "",
            "**Recommendations**",
            *[f"{i}. {a}" for i, a in enumerate(r.recommended_actions, 1)],
        ]
    )
    return clean(mrkdwn(md))


def parent_blocks(
    t: Investigation, buttons: bool, client: str | None = None, jira: str | None = None
) -> list[dict[str, Any]]:
    """Always sent in full, so no stale buttons survive an update. Each button
    names its pause (the deadline): a late click can't decide a later pause.
    client: the Contract's client channel, for the Send to client button.
    jira: the Contract's Jira project, for the Create Jira issue button."""
    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": parent_text(t)}}
    ]
    done: list[dict[str, Any]] = []  # buttons on a finished Report
    if buttons and client and t.report and not t.client_sent_at:  # a Report: done
        send = {
            "type": "button",
            "action_id": "send_to_client",
            "text": {"type": "plain_text", "text": "Send to client"},
            "value": json.dumps({"id": t.id}),
            "confirm": {
                "title": {"type": "plain_text", "text": "Send to the client?"},
                "text": {
                    "type": "plain_text",
                    "text": f"The Report, without Evidence, goes to the client channel {client}.",
                },
                "confirm": {"type": "plain_text", "text": "Send"},
                "deny": {"type": "plain_text", "text": "Cancel"},
            },
        }
        done.append(send)
    if buttons and jira and t.report and t.status == "done" and not t.jira_at:
        file = {
            "type": "button",
            "action_id": "create_jira",
            "text": {"type": "plain_text", "text": "Create Jira issue"},
            "value": json.dumps({"id": t.id}),
            "confirm": {
                "title": {"type": "plain_text", "text": "Create a Jira issue?"},
                "text": {
                    "type": "plain_text",
                    "text": f"The full Report, with Evidence, goes to Jira project {jira}.",
                },
                "confirm": {"type": "plain_text", "text": "Create"},
                "deny": {"type": "plain_text", "text": "Cancel"},
            },
        }
        done.append(file)
    if done:
        blocks.append({"type": "actions", "elements": done})
    if buttons and t.status == "awaiting_approval":
        value = json.dumps({"id": t.id, "deadline": t.deadline})
        names = ", ".join(sorted({p["name"] for p in t.pending}))
        approve = {
            "type": "button",
            "action_id": "approve",
            "text": {"type": "plain_text", "text": "Approve"},
            "style": "primary",
            "value": value,
            "confirm": {
                "title": {"type": "plain_text", "text": "Run these actions?"},
                "text": {"type": "plain_text", "text": names[:300]},
                "confirm": {"type": "plain_text", "text": "Approve"},
                "deny": {"type": "plain_text", "text": "Cancel"},
            },
        }
        reject = {
            "type": "button",
            "action_id": "reject",
            "text": {"type": "plain_text", "text": "Reject"},
            "style": "danger",
            "value": value,
        }
        blocks.append({"type": "actions", "elements": [approve, reject]})
    return blocks


def reject_modal(metadata: str) -> dict[str, Any]:
    return {
        "type": "modal",
        "callback_id": "reject",
        "private_metadata": metadata,
        "title": {"type": "plain_text", "text": "Reject"},
        "submit": {"type": "plain_text", "text": "Reject"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "reason",
                "optional": True,
                "label": {"type": "plain_text", "text": "Why? The agent reads this."},
                "element": {"type": "plain_text_input", "action_id": "reason", "multiline": True},
            }
        ],
    }


def reply_text(t: Investigation, buttons: bool = False) -> str | None:
    if t.status == "awaiting_approval":
        actions = "\n".join(f"• {clean(p['description'], 2000)}" for p in t.pending)
        decide = f"Decide with `POST /investigations/{t.id}/decision`."
        if buttons:
            decide = f"Approve or reject on the message above, or {decide[0].lower()}{decide[1:]}"
        return f"Waiting for your approval:\n{actions}\n{decide}"
    if t.status == "done" and t.report:
        return clean(mrkdwn(t.report.to_markdown(t.executed_actions)))
    if t.status == "done" and t.answer:
        return clean(mrkdwn(t.answer.to_markdown()))
    if t.status == "failed":
        return f"Investigation failed: {clean(t.error or 'unknown error', 2000)}"
    return None


class Slack:
    def __init__(self, token: SecretStr | None, http: httpx.AsyncClient) -> None:
        self.token, self.http = token, http

    async def _call(
        self, method: str, payload: dict[str, Any], token: SecretStr | None = None
    ) -> dict[str, Any] | None:
        token = token or self.token
        assert token is not None
        headers = {"Authorization": f"Bearer {token.get_secret_value()}"}
        where = payload.get("channel", "-")
        for attempt in (1, 2):
            try:
                r = await self.http.post(API + method, json=payload, headers=headers, timeout=10)
            except httpx.HTTPError as e:
                log.warning("slack %s to %s: %s", method, where, type(e).__name__)
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
                log.warning("slack %s to %s failed: %s", method, where, error)
                return None
            return body
        return None

    async def post(
        self,
        channel: str,
        text: str,
        thread_ts: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
    ) -> str | None:
        """The message's ts, or None when it wasn't posted. With blocks, text is
        the notification's fallback."""
        payload: dict[str, Any] = {"channel": channel, "text": text, "unfurl_links": False}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        if blocks is not None:
            payload["blocks"] = blocks
        body = await self._call("chat.postMessage", payload)
        return str(body["ts"]) if body else None

    async def update(
        self, channel: str, ts: str, text: str, blocks: list[dict[str, Any]] | None = None
    ) -> None:
        payload: dict[str, Any] = {"channel": channel, "ts": ts, "text": text}
        if blocks is not None:
            payload["blocks"] = blocks
        await self._call("chat.update", payload)

    async def ephemeral(self, channel: str, user: str, text: str) -> None:
        await self._call("chat.postEphemeral", {"channel": channel, "user": user, "text": text})

    async def open_view(self, trigger_id: str, view: dict[str, Any]) -> None:
        await self._call("views.open", {"trigger_id": trigger_id, "view": view})

    async def listen(
        self, app_token: SecretStr, handle: Callable[[str, dict[str, Any]], None]
    ) -> None:
        """Socket Mode until cancelled: ask for a websocket URL, ack every envelope
        before handling it (Slack wants the ack within 3s), and reconnect when Slack
        says disconnect (it does every few hours) or the socket drops. handle must
        not block: it gets each envelope's type ("interactive" for clicks,
        "events_api" for mentions) and payload, and spawns the work."""
        backoff = 1.0
        while True:
            try:
                body = await self._call("apps.connections.open", {}, app_token)
                if body:
                    url = body["url"]
                    # httpx's CA bundle (certifi): the system's may be missing (macOS).
                    tls = httpx.create_ssl_context() if url.startswith("wss:") else None
                    async with websockets.connect(url, ssl=tls) as ws:
                        backoff = 1.0
                        async for raw in ws:
                            msg = json.loads(raw)
                            if "envelope_id" in msg:
                                await ws.send(json.dumps({"envelope_id": msg["envelope_id"]}))
                            if msg.get("type") == "disconnect":
                                break
                            if msg.get("type") in ("interactive", "events_api"):
                                handle(msg["type"], msg["payload"])
            except Exception as e:  # the Hub runs on without buttons; keep trying
                log.warning("slack socket mode: %s", type(e).__name__)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
