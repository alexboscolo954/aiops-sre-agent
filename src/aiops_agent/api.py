"""Alertmanager webhook receiver for every Contract.

POST /contracts/{id}/alertmanager  That Contract's Alertmanager (its own webhook token).
                                Starts a triage, or makes a resolved group's
                                proposed actions stale. Unknown id = wrong token = 401.
GET  /investigations[/{id}]     Status, report, pending actions (approver token).
POST /investigations/{id}/decision  Approve or reject pending actions (approver token).
                                The same decision path as the Slack buttons.
GET  /healthz, /metrics

State lives in Postgres (store.py): Investigations, the dedup memory, every
Approval decision and the LangGraph checkpoints, so a pending approval survives a
restart. ponytail: timers and the concurrency limit are per process, so run one
replica; several would each re-arm the same deadlines (harmless: claims are
atomic) but share no limit.
"""

import asyncio
import json
import logging
import re
import secrets
import uuid
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from aiops_agent import agent, contracts
from aiops_agent.config import Settings
from aiops_agent.models import AlertGroup, Investigation
from aiops_agent.observability import PENDING_APPROVALS, TRIAGE_SECONDS, TRIAGES
from aiops_agent.slack import (
    Slack,
    clean,
    client_text,
    parent_blocks,
    parent_text,
    reject_modal,
    reply_text,
)
from aiops_agent.store import Store, connect, now

log = logging.getLogger("aiops.api")
DEDUP_SECONDS = 30 * 60


class Decision(BaseModel):
    approve: bool
    message: str = ""


def create_app(
    settings: Settings | None = None,
    model: BaseChatModel | None = None,
    mcp_factory: Any = None,
    by_id: dict[str, contracts.Contract] | None = None,
    slack_http: httpx.AsyncClient | None = None,
) -> FastAPI:
    """mcp_factory(contract) -> Toolbox, by_id (the loaded Contracts) and slack_http
    (an httpx client for Slack's Web API), for tests."""
    settings = settings or Settings()
    if not settings.approver_token:
        raise RuntimeError("set AIOPS_APPROVER_TOKEN")
    approver_token = settings.approver_token.get_secret_value()
    if by_id is None:
        if not settings.contracts_dir:
            raise RuntimeError("set AIOPS_CONTRACTS_DIR")
        by_id = contracts.load(settings.contracts_dir)
    for c in by_id.values():
        if contracts.token_matches(c, approver_token):
            raise RuntimeError(f"Contract {c.id!r}'s webhook token is the approver token")
    if not settings.database_url:
        raise RuntimeError("set AIOPS_DATABASE_URL")
    database_url = settings.database_url.get_secret_value()
    operator = settings.slack_operator_id
    if settings.slack_app_token and not (
        settings.slack_bot_token and operator and re.fullmatch(r"[UW][A-Z0-9]{8,}", operator)
    ):
        raise RuntimeError(
            "AIOPS_SLACK_APP_TOKEN needs AIOPS_SLACK_BOT_TOKEN and AIOPS_SLACK_OPERATOR_ID (U...)"
        )
    buttons = settings.slack_app_token is not None
    model = model or agent.build_model(settings)
    if mcp_factory is None:
        mcp_factory = lambda c: agent.build_mcp(c, settings)  # noqa: E731
    db: dict[str, Any] = {}  # store and checkpointer, opened in the lifespan
    slots = asyncio.Semaphore(settings.max_concurrent_triages)
    tasks: set[asyncio.Task[None]] = set()

    def store() -> Store:
        st: Store = db["store"]
        return st

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        async with connect(database_url) as pool, slack_http or httpx.AsyncClient() as http:
            db["slack"] = Slack(settings.slack_bot_token, http)
            db["store"] = Store(pool)
            await store().migrate()
            db["checkpointer"] = AsyncPostgresSaver(pool)
            await db["checkpointer"].setup()
            await recover()
            if settings.slack_app_token:
                spawn(db["slack"].listen(settings.slack_app_token, lambda p: spawn(interact(p))))
            try:
                yield
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="aiops-sre-agent", lifespan=lifespan)
    bearer = HTTPBearer()

    def check(creds: HTTPAuthorizationCredentials, expected: str) -> None:
        if not secrets.compare_digest(creds.credentials.encode(), expected.encode()):
            raise HTTPException(401, "invalid token")

    def approver_auth(creds: HTTPAuthorizationCredentials = Depends(bearer)) -> None:  # noqa: B008
        check(creds, approver_token)

    async def notify(t: Investigation) -> None:
        log.info("investigation %s %s", t.id, t.status)
        PENDING_APPROVALS.set(await store().pending_count())
        if t.status in ("done", "failed"):
            TRIAGES.labels(t.status).inc()
            TRIAGE_SECONDS.observe(now() - t.started)
        await to_slack(t)

    async def to_slack(t: Investigation, note: str | None = None) -> None:
        """The Investigation's thread in its own Contract's channel: start it if it has
        none yet (or the first post failed), keep the parent's status (and buttons)
        current, and reply with the note and anything the Operator should read."""
        contract = by_id.get(t.contract_id)
        channel = t.slack_channel or (
            contract.slack.operator_channel if contract and contract.slack else None
        )
        if not channel or not settings.slack_bot_token:
            return
        slack: Slack = db["slack"]
        blocks = parent_blocks(t, buttons, client_channel(t))
        if t.slack_ts is None:
            ts = await slack.post(channel, parent_text(t), blocks=blocks)
            if ts and await store().set_slack_thread(t.id, channel, ts):
                t.slack_channel, t.slack_ts = channel, ts
        else:
            await slack.update(channel, t.slack_ts, parent_text(t), blocks)
        if not t.slack_ts:
            return
        for reply in (note, reply_text(t, buttons)):
            if reply:
                await slack.post(channel, reply, thread_ts=t.slack_ts)

    async def fail(t: Investigation, error: str) -> None:
        t.status, t.error, t.pending, t.deadline = "failed", error, [], None
        await store().save(t)
        await notify(t)

    async def recover() -> None:
        """After a restart. A Run that was cut off is never replayed: if it was resuming
        an approval, the write may already have run, and replaying could run it twice."""
        for t in await store().unfinished():
            if t.contract_id not in by_id:
                await fail(t, f"Contract {t.contract_id!r} is no longer configured")
            elif t.status == "running":
                error = (
                    "The Hub restarted during this run. It was not resumed, so nothing runs twice."
                )
                last = await store().last_decision(t.id)
                if last and last["approve"]:
                    names = ", ".join(a["name"] for a in last["actions"])
                    error += (
                        f" The approved actions ({names}) may or may not have run:"
                        " check the cluster."
                    )
                await fail(t, error)
            elif t.group_resolved:
                await reject_stale(t.id, t.deadline, "The alert group resolved before a decision")
            else:
                spawn(expire(t.id, t.deadline))  # a deadline already past fires at once

    def apply(t: Investigation, outcome: agent.Outcome) -> None:
        t.report, t.pending = outcome.report, outcome.pending
        t.executed_actions = outcome.executed_actions
        t.status = "done" if outcome.done else "awaiting_approval"
        t.deadline = now() + settings.decision_timeout_seconds if t.pending else None

    async def run(t: Investigation, step: Any, note: str | None = None) -> None:
        await to_slack(t, note)  # "investigating", in a new or the existing thread
        async with slots:
            try:
                # Always the Investigation's own Contract, on start and on every resume.
                toolbox = mcp_factory(by_id[t.contract_id])

                async def record(tool: str, args: dict[str, Any], result: str, error: bool) -> None:
                    await store().record_tool_call(t.id, t.contract_id, tool, args, result, error)

                checkpointer = db["checkpointer"]
                async with agent.open_agent(settings, toolbox, model, checkpointer, record) as a:
                    apply(t, await step(a))
            except Exception as e:  # report every failure, never lose an alert silently
                log.exception("investigation %s failed", t.id)
                t.status, t.error, t.pending, t.deadline = (
                    "failed",
                    f"{type(e).__name__}: {e}",
                    [],
                    None,
                )
        await store().save(t)
        if t.status == "awaiting_approval":
            fresh = await store().get(t.id)  # the group may have resolved during the Run
            if fresh and fresh.group_resolved:
                await reject_stale(t.id, t.deadline, "The alert group resolved before a decision")
                return  # no one to ask; the resumed run reports
        await notify(t)
        if t.status == "awaiting_approval":
            spawn(expire(t.id, t.deadline))

    async def expire(investigation_id: str, deadline: float | None) -> None:
        await asyncio.sleep(max(0.0, (deadline or 0) - now()))
        await reject_stale(
            investigation_id, deadline, f"No decision within {settings.decision_timeout_seconds}s"
        )

    async def settle(
        t: Investigation,
        deadline: float | None,
        approve: bool,
        message: str,
        decided_by: str,
        note: str,
    ) -> bool:
        """The one decision path (API, Slack buttons, Stale): claim the pause named
        by its deadline, record who decided, resume. False when that pause is
        already decided, Stale, or not the current one."""
        pending = await store().claim(t.id, deadline)
        if pending is None:
            return False
        log.info(
            "investigation %s decision approve=%s by %s actions=%s",
            t.id,
            approve,
            decided_by,
            [p["name"] for p in pending],
        )
        await store().record_decision(t.id, approve, pending, message, decided_by)
        decisions: list[dict[str, Any]] = [
            {"type": "approve"} if approve else {"type": "reject", "message": message}
            for _ in pending
        ]
        t.status, t.pending, t.deadline = "running", [], None
        spawn(run(t, lambda a: agent.resume(a, t.id, decisions), note))
        return True

    async def reject_stale(investigation_id: str, deadline: float | None, reason: str) -> bool:
        """A stale proposed action is rejected automatically; the investigation still
        ends with a report. False when someone else already decided this pause."""
        t = await store().get(investigation_id)
        if t is None:
            return False
        msg = f"{reason}. The action was not executed. Do not retry; finish the report."
        note = f":hourglass: Stale, rejected automatically: {clean(reason, 500)}."
        return await settle(t, deadline, False, msg, "stale", note)

    async def interact(p: dict[str, Any]) -> None:
        try:
            await interaction(p)
        except Exception:  # a malformed payload must not vanish silently
            log.exception("slack interaction %s failed", p.get("type"))

    def client_channel(t: Investigation) -> str | None:
        """From the loaded Contract, never from a click: the config decides."""
        contract = by_id.get(t.contract_id)
        return contract.slack.client_channel if contract and contract.slack else None

    async def send_to_client(t: Investigation, channel: str, user: str) -> None:
        """The Client report, once: claim, post as plain text (no blocks, so no
        controls), then take the button away. ponytail: a crash between the claim
        and the post leaves it marked sent but unsent; check the client channel."""
        slack: Slack = db["slack"]
        client = client_channel(t)
        at = await store().claim_client_report(t.id, f"slack:{user}") if client else None
        if not client or at is None:
            await slack.ephemeral(channel, user, "Already sent, or nothing to send.")
            return
        if await slack.post(client, client_text(t)) is None:
            await store().release_client_report(t.id, at)
            await slack.ephemeral(channel, user, "Slack refused the post: nothing was sent.")
            return
        t.client_sent_at, t.client_sent_by = at, f"slack:{user}"
        log.info("investigation %s client report sent by %s", t.id, t.client_sent_by)
        assert t.slack_ts is not None  # the click came from this thread's parent
        await slack.update(channel, t.slack_ts, parent_text(t), parent_blocks(t, buttons, client))
        await slack.post(channel, f":outbox_tray: Sent to the client by <@{user}>.", t.slack_ts)

    async def interaction(p: dict[str, Any]) -> None:
        """A Slack button click or reject modal, from Socket Mode (already acked)."""
        slack: Slack = db["slack"]
        user = p.get("user", {}).get("id", "")
        if p.get("type") == "block_actions":
            action = p["actions"][0]
            pause, channel = json.loads(action["value"]), p["channel"]["id"]
        elif p.get("type") == "view_submission" and p["view"]["callback_id"] == "reject":
            pause = json.loads(p["view"]["private_metadata"])
            channel, action = pause["channel"], {"action_id": "reject_submit"}
        else:
            return
        if user != operator:
            await slack.ephemeral(channel, user, "Only the Operator can decide.")
            return
        t = await store().get(pause["id"])
        # A button only decides its own Investigation, from its own Contract's channel.
        if t is None or t.slack_channel != channel:
            await slack.ephemeral(channel, user, "That Investigation isn't in this channel.")
            return
        if action["action_id"] == "send_to_client":
            await send_to_client(t, channel, user)
            return
        deadline = pause["deadline"]
        by, who = f"slack:{user}", f"<@{user}>"
        if action["action_id"] == "approve":
            done = await settle(t, deadline, True, "", by, f":white_check_mark: Approved by {who}.")
        elif action["action_id"] == "reject":
            # Claim only on submit: a cancelled modal leaves the pause undecided.
            done = t.status == "awaiting_approval" and t.deadline == deadline
            if done:
                meta = json.dumps({**pause, "channel": channel})
                await slack.open_view(p["trigger_id"], reject_modal(meta))
        else:
            reason = (p["view"]["state"]["values"]["reason"]["reason"].get("value") or "").strip()
            message = reason or "Rejected by the Operator. Do not retry."
            shown = f": {clean(reason, 2000)}" if reason else ""
            done = await settle(
                t, deadline, False, message, by, f":no_entry: Rejected by {who}{shown}"
            )
        if not done:
            await slack.ephemeral(channel, user, "Already decided or Stale: nothing to decide.")

    def spawn(coro: Any) -> None:
        task = asyncio.create_task(coro)
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    @app.post("/contracts/{contract_id}/alertmanager", status_code=202)
    async def alertmanager(
        contract_id: str,
        group: AlertGroup,
        creds: HTTPAuthorizationCredentials = Depends(bearer),  # noqa: B008
    ) -> dict[str, Any]:
        if not contracts.token_matches(by_id.get(contract_id), creds.credentials):
            raise HTTPException(401, "invalid token")  # also for an unknown Contract
        if not group.firing:
            # Still investigating ones go stale when they pause (see run()).
            same_group = await store().mark_group_resolved(contract_id, group.groupKey)
            stale = [
                t.id
                for t in same_group
                if t.status == "awaiting_approval"
                and await reject_stale(
                    t.id, t.deadline, "The alert group resolved before a decision"
                )
            ]
            if stale:
                return {"status": "stale", "investigations": stale}
            return {"status": "ignored", "reason": "no firing alerts"}
        firing = {a.fingerprint for a in group.firing}
        started = now()
        seen: set[str] = set()
        # Two Contracts can send the same group key: the memory is per Contract.
        remembered = await store().alert_group(contract_id, group.groupKey)
        if remembered and started - remembered[0] <= DEDUP_SECONDS:
            _, previous, seen = remembered
            # Alertmanager re-sends on every repeat_interval and when an Alert resolves.
            # Only an Alert not seen before is new work.
            if firing <= seen:
                return {"status": "duplicate", "investigation": previous}

        t = Investigation(
            id=str(uuid.uuid4()),
            contract_id=contract_id,
            title=group.title,
            group_key=group.groupKey,
            started=started,
        )
        await store().insert(t)
        await store().remember_group(contract_id, group.groupKey, started, t.id, seen | firing)
        spawn(run(t, lambda a: agent.start(a, group, t.id)))
        return {"status": "accepted", "investigation": t.id}

    @app.get("/investigations", dependencies=[Depends(approver_auth)])
    async def list_investigations() -> list[Investigation]:
        return await store().recent(50)

    @app.get("/investigations/{investigation_id}", dependencies=[Depends(approver_auth)])
    async def get_investigation(investigation_id: str) -> Investigation:
        t = await store().get(investigation_id)
        if t is None:
            raise HTTPException(404, "unknown investigation")
        return t

    @app.post(
        "/investigations/{investigation_id}/decision",
        status_code=202,
        dependencies=[Depends(approver_auth)],
    )
    async def decide(investigation_id: str, decision: Decision) -> dict[str, str]:
        t = await store().get(investigation_id)
        if t is None:
            raise HTTPException(404, "unknown investigation")
        if decision.approve:
            message, note = "", ":white_check_mark: Approved through the API."
        else:
            message = decision.message or "Rejected by the Operator. Do not retry."
            shown = f": {clean(decision.message, 2000)}" if decision.message else ""
            note = f":no_entry: Rejected through the API{shown}"
        decided = t.status == "awaiting_approval" and await settle(
            t, t.deadline, decision.approve, message, "operator", note
        )
        if not decided:  # already decided, stale, or never paused
            current = await store().get(t.id)
            status = current.status if current else t.status
            raise HTTPException(409, f"investigation is {status}, nothing to decide")
        return {"status": "resumed"}

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics(request: Request) -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app
