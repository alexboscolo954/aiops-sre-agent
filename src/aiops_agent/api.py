"""Alertmanager webhook receiver for every Contract.

POST /contracts/{id}/alertmanager  That Contract's Alertmanager (its own webhook token).
POST /contracts/{id}/grafana       That Contract's Grafana Alerting, same token, normalized
                                   into the same Alert group.
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
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastmcp import Client
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from aiops_agent import agent, console, contracts, related
from aiops_agent.config import Settings
from aiops_agent.contracts import Jira
from aiops_agent.models import AlertGroup, GrafanaAlertGroup, Investigation
from aiops_agent.observability import PENDING_APPROVALS, TRIAGE_SECONDS, TRIAGES
from aiops_agent.safety import redact_capped
from aiops_agent.servers import jira
from aiops_agent.slack import (
    STATUS,
    Slack,
    clean,
    client_text,
    parent_blocks,
    parent_text,
    reject_modal,
    related_blocks,
    related_text,
    reply_text,
)
from aiops_agent.store import Store, connect, now

log = logging.getLogger("aiops.api")
DEDUP_SECONDS = 30 * 60
PROBE_SECONDS = 10  # each health check


def usd(amount: float) -> str:
    """Cents above a dollar, tenths of a cent below: small spends stay visible."""
    return f"${amount:.2f}" if amount >= 1 else f"${amount:.4f}"


def shown_settings(settings: Settings) -> dict[str, Any]:
    """The Hub's settings for the console. pydantic masks SecretStr fields; these
    two can carry credentials as plain strings, so they're masked here too."""
    shown = settings.model_dump(mode="json")
    shown["model_headers"] = {name: "**********" for name in settings.model_headers}
    if settings.model_base_url:
        url = urlsplit(settings.model_base_url)
        if url.username or url.password:
            host = url.netloc.rsplit("@", 1)[1]
            shown["model_base_url"] = url._replace(netloc=f"**********@{host}").geturl()
    return shown


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
    hub_provider = settings.model.split(":", 1)[0]
    for c in by_id.values():
        effective = c.model or settings.model
        if c.monthly_budget_usd and effective not in settings.model_prices:
            raise RuntimeError(
                f"Contract {c.id!r} has a budget, but its model {effective!r} has no price "
                "in AIOPS_MODEL_PRICES"
            )
        if c.model and settings.model_base_url and c.model.split(":", 1)[0] != hub_provider:
            raise RuntimeError(
                f"Contract {c.id!r}'s model {c.model!r} would go through the Hub's gateway "
                f"(AIOPS_MODEL_BASE_URL): use a {hub_provider}: model, as AIOPS_MODEL does"
            )
    models: dict[str, BaseChatModel] = {}  # per Contract, built once

    def model_for(c: contracts.Contract) -> BaseChatModel:
        if model is not None:  # tests: one scripted model for every Contract
            return model
        if c.id not in models:
            models[c.id] = agent.build_model(agent.for_contract(settings, c))
        return models[c.id]

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
            db["http"] = http  # no default headers: each caller sets its own auth
            db["store"] = Store(pool)
            await store().migrate()
            db["checkpointer"] = AsyncPostgresSaver(pool, serde=agent.CHECKPOINT_SERDE)
            app.state.checkpointer = db["checkpointer"]  # for tests
            await db["checkpointer"].setup()
            await recover()
            if settings.slack_app_token:
                spawn(db["slack"].listen(settings.slack_app_token, on_socket))
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
        if t.kind == "question":
            # The thread's root is the Operator's own message: never post or edit a
            # parent, only reply. A Question never pauses, so it has no buttons.
            if t.slack_ts:
                status = reply_text(t) or f"{STATUS[t.status]} · `{t.id}`"
                await slack.post(channel, status, thread_ts=t.slack_ts)
            return
        blocks = parent_blocks(t, buttons, client_channel(t), jira_project(t))
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

    async def over_budget(contract_id: str) -> str | None:
        """Why a new Run may not start: the Contract has spent its monthly budget.
        Checked only where a new Run would start, never on a resume (an approved
        action must still be reported). ponytail: Runs that start together can all
        pass the check and overshoot; a reservation per Run if that ever matters."""
        budget = by_id[contract_id].monthly_budget_usd
        spent = await store().month_spend(contract_id, now()) if budget else 0.0
        if not budget or spent < budget:
            return None
        return (
            f"Contract {contract_id!r} has used its monthly budget: {usd(spent)} of "
            f"{usd(budget)}. New Investigations are refused until next month, or until "
            "monthly_budget_usd is raised."
        )

    async def refuse(t: Investigation, reason: str) -> None:
        """No Run, no model call: the Operator still hears about it (fail notifies)."""
        log.warning("investigation %s refused: %s", t.id, reason)
        await fail(t, reason)
        await budget_notices(t.contract_id)

    async def budget_notices(contract_id: str) -> None:
        """80% and 100% of the month's budget, each posted once per Contract per month
        in its operator channel (logged when it has none)."""
        c = by_id[contract_id]
        if not c.monthly_budget_usd:
            return
        at = now()
        spent = await store().month_spend(c.id, at)
        for level in (80, 100):
            if spent < c.monthly_budget_usd * level / 100:
                continue
            if not await store().notice_once(c.id, at, level):
                continue
            if level == 100:
                text = (
                    f":no_entry: *[{clean(c.id)}]* has used its monthly budget: "
                    f"{usd(spent)} of {usd(c.monthly_budget_usd)}. New Investigations are "
                    "refused until next month, or until `monthly_budget_usd` is raised."
                )
            else:
                text = (
                    f":warning: *[{clean(c.id)}]* has used {level}% of its monthly budget: "
                    f"{usd(spent)} of {usd(c.monthly_budget_usd)}."
                )
            log.warning("budget %s %d%%: %.4f of %.2f", c.id, level, spent, c.monthly_budget_usd)
            if c.slack and settings.slack_bot_token:
                await db["slack"].post(c.slack.operator_channel, text)

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
        t.report, t.answer, t.pending = outcome.report, outcome.answer, outcome.pending
        t.executed_actions = outcome.executed_actions
        t.status = "done" if outcome.done else "awaiting_approval"
        t.deadline = now() + settings.decision_timeout_seconds if t.pending else None

    def agent_kind(t: Investigation) -> agent.Kind:
        return "question" if t.kind == "question" else "triage"  # Checks come in 8.1

    async def run(t: Investigation, step: Any, note: str | None = None) -> None:
        await to_slack(t, note)  # "investigating", in a new or the existing thread
        async with slots:
            try:
                # Always the Investigation's own Contract, on start and on every resume.
                toolbox = mcp_factory(by_id[t.contract_id])

                async def record(tool: str, args: dict[str, Any], result: str, error: bool) -> None:
                    await store().record_tool_call(t.id, t.contract_id, tool, args, result, error)

                contract = by_id[t.contract_id]
                name = contract.model or settings.model
                price = settings.model_prices.get(name)

                async def used(input_tokens: int, output_tokens: int) -> None:
                    cost = price.cost(input_tokens, output_tokens) if price else None
                    await store().record_usage(
                        t.id, t.contract_id, name, input_tokens, output_tokens, cost
                    )

                checkpointer = db["checkpointer"]
                async with agent.open_agent(
                    settings,
                    toolbox,
                    model_for(contract),
                    checkpointer,
                    record,
                    kind=agent_kind(t),
                    usage=used,
                ) as a:
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
        await budget_notices(t.contract_id)
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

    def jira_of(t: Investigation) -> Jira | None:
        """From the loaded Contract, never from a click."""
        contract = by_id.get(t.contract_id)
        found = [i for i in contract.integrations if isinstance(i, Jira)] if contract else []
        return found[0] if found else None

    def jira_project(t: Investigation) -> str | None:
        j = jira_of(t)
        return j.project if j else None

    async def file_jira(t: Investigation, by: str, who: str) -> tuple[str | None, str]:
        """The Report as an issue in the Contract's Jira project, once, from the Slack
        button or the console: claim, create, record. A refusal frees the claim for a
        retry; no answer keeps it, since Jira may have created the issue. Then the
        Slack thread, if any, shows it. Returns (key, what to tell the Operator).
        ponytail: an unknown outcome keeps the claim for good (no duplicate issue);
        clearing jira_at in the database is the only reset, after checking Jira."""
        j = jira_of(t)
        at = await store().claim_jira(t.id, by) if j and t.report else None
        if j is None or t.report is None or at is None:
            return None, "Already filed (or being filed), or nothing to file."
        token = by_id[t.contract_id].secret(j.token_secret)
        summary = jira.issue_summary(t.report)
        document = jira.report_document(t.report, t.executed_actions, t.id)
        try:
            key = await jira.create_issue(
                db["http"], j.url, j.email, token, j.project, j.issue_type, summary, document
            )
        except jira.Refused as e:
            await store().release_jira(t.id, at)
            return None, f"Jira refused the issue ({clean(str(e), 500)}): nothing was created."
        except jira.Unknown as e:
            log.warning("investigation %s: Jira create got no answer: %s", t.id, e)
            return None, (
                f"Jira didn't answer ({e}): it may have created the issue. "
                f"Check project {j.project} before filing it by hand."
            )
        await store().set_jira_issue(t.id, at, key)
        t.jira_issue, t.jira_by, t.jira_at = key, by, at
        log.info("investigation %s filed as %s by %s", t.id, key, by)
        if t.slack_channel and t.slack_ts and settings.slack_bot_token:
            slack: Slack = db["slack"]
            blocks = parent_blocks(t, buttons, client_channel(t), j.project)
            await slack.update(t.slack_channel, t.slack_ts, parent_text(t), blocks)
            url = f"{j.url.rstrip('/')}/browse/{key}"
            await slack.post(
                t.slack_channel, f":ticket: Filed as {key} by {who}: {url}", t.slack_ts
            )
        return key, f"Filed as {key}."

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
        blocks = parent_blocks(t, buttons, client, jira_project(t))
        await slack.update(channel, t.slack_ts, parent_text(t), blocks)
        await slack.post(channel, f":outbox_tray: Sent to the client by <@{user}>.", t.slack_ts)

    async def triage_separately(
        t: Investigation, related_id: int, channel: str, user: str, message_ts: str | None
    ) -> None:
        """A Related alert group of t gets its own Triage, once: claimed together with
        that Triage, so a double click starts one. The budget is checked before the
        claim, so a refusal leaves the button for later. From then on the group is
        that Triage's own: its re-sends, resolution and Stale rule go there.
        ponytail: a group that resolved before the click isn't tracked, so its
        Triage starts as firing; track related groups' resolution if that matters."""
        slack: Slack = db["slack"]
        row = await store().related_group(related_id, t.id)
        gone = "Already triaged separately, or not a related group of this Triage."
        if row is None:
            await slack.ephemeral(channel, user, gone)
            return
        if reason := await over_budget(t.contract_id):
            await slack.ephemeral(channel, user, f"Not started. {reason}")
            return
        group = AlertGroup.model_validate(row["input"])
        new = Investigation(
            id=str(uuid.uuid4()),
            contract_id=t.contract_id,
            title=row["title"],
            group_key=row["group_key"],
            started=now(),
            input=row["input"],
        )
        if not await store().separate(related_id, t.id, new):
            await slack.ephemeral(channel, user, gone)
            return
        remembered = await store().alert_group(t.contract_id, new.group_key)
        seen = remembered[2] if remembered else {a.fingerprint for a in group.firing}
        await store().remember_group(t.contract_id, new.group_key, new.started, new.id, seen)
        log.info("related group %s of %s triaged separately as %s", related_id, t.id, new.id)
        if message_ts:  # the post clicked: its button goes, the rest stays
            severity = related.labels(group).get("severity")
            text = related_text(row["title"], row["matched"], severity, row["louder"])
            await slack.update(channel, message_ts, f"{text}\n:mag: Triaged separately.", [])
        title = clean(row["title"], 200)
        assert t.slack_ts is not None  # the click came from this thread
        reply = f":mag: <@{user}> had *{title}* triaged separately, in a new thread."
        await slack.post(channel, reply, t.slack_ts)
        spawn(run(new, lambda a: agent.start(a, group, new.id)))

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
        if action["action_id"] == "triage_separately":
            message_ts = p.get("container", {}).get("message_ts")
            await triage_separately(t, int(pause["related"]), channel, user, message_ts)
            return
        if action["action_id"] == "create_jira":
            key, message = await file_jira(t, f"slack:{user}", f"<@{user}>")
            if key is None:
                await slack.ephemeral(channel, user, message)
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

    by_channel = {c.slack.operator_channel: c for c in by_id.values() if c.slack}
    client_channels = {c.slack.client_channel for c in by_id.values() if c.slack}

    def on_socket(kind: str, payload: dict[str, Any]) -> None:
        spawn(interact(payload) if kind == "interactive" else mention(payload))

    async def mention(p: dict[str, Any]) -> None:
        try:
            await on_mention(p.get("event", {}))
        except Exception:  # a malformed event must not vanish silently
            log.exception("slack mention failed")

    async def on_mention(event: dict[str, Any]) -> None:
        """@aiops in a Contract's operator channel: a new Question, or in a Question's
        thread, a follow-up on it. Only the Operator, and never in a client channel."""
        if event.get("type") != "app_mention":
            return
        slack: Slack = db["slack"]
        user, channel, ts = event["user"], event["channel"], event["ts"]
        root = event.get("thread_ts") or ts
        if user != operator:
            await slack.ephemeral(channel, user, "Only the Operator can ask.")
            return
        contract = by_channel.get(channel)
        if contract is None:
            where = "the client sees this channel" if channel in client_channels else "no Contract"
            await slack.ephemeral(channel, user, f"Ask in a Contract's operator channel ({where}).")
            return
        text = re.sub(r"^(\s*<@[UW][A-Z0-9]+>)+\s*", "", event.get("text", ""))[:4000].strip()
        if not text:
            await slack.ephemeral(channel, user, "Ask a question after the mention.")
            return
        t = await store().by_thread(channel, root)
        if t is None:
            await start_question(contract.id, text, ts, channel, root)  # None: redelivered
        elif t.kind != "question":
            await slack.ephemeral(channel, user, "Follow-ups work in Question threads only.")
        elif not await follow_up(t, text, ts) and t.last_mention_ts != ts:
            # Still running. A redelivery of the mention it's answering needs no reply.
            await slack.ephemeral(channel, user, "Still answering the last one: ask again after.")

    async def start_question(
        contract_id: str,
        text: str,
        asked_ts: str,
        channel: str | None = None,
        root: str | None = None,
    ) -> Investigation | None:
        """A new Question, from Slack (its thread) or the console (no thread). None
        when its Slack thread already has one (a redelivered mention)."""
        t = Investigation(
            id=str(uuid.uuid4()),
            kind="question",
            contract_id=contract_id,
            title=text[:200],
            started=now(),
            slack_channel=channel,
            slack_ts=root,
            last_mention_ts=asked_ts,
            input={"question": text},
        )
        if not await store().insert_question(t):
            return None
        if reason := await over_budget(contract_id):
            await refuse(t, reason)
            return t
        log.info("question %s for %s", t.id, contract_id)
        spawn(run(t, lambda a: agent.ask(a, text, t.id)))
        return t

    async def follow_up(t: Investigation, text: str, asked_ts: str) -> bool:
        """One more message on a finished Question; False while it's still running,
        or when asked_ts isn't newer than the last ask (a redelivery)."""
        if not await store().claim_follow_up(t.id, asked_ts):
            return False
        t.status, t.error, t.last_mention_ts = "running", None, asked_ts
        if reason := await over_budget(t.contract_id):
            await refuse(t, reason)
            return True
        log.info("question %s follow-up", t.id)
        spawn(run(t, lambda a: agent.ask(a, text, t.id)))
        return True

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
        contract = by_id[contract_id]
        window = 60 * (contract.related.window_minutes or settings.related_window_minutes)
        candidates = await store().open_triages(contract_id, started - window, group.groupKey)
        if match := related.find(group, candidates, contract.related):
            # Remembered under the Triage it joined: its re-sends are duplicates of it.
            t = match.investigation
            rid = await store().add_related(
                t.id, contract_id, group, match.matched, match.louder, started
            )
            await store().remember_group(contract_id, group.groupKey, started, t.id, seen | firing)
            log.info("alert group %s joined investigation %s", group.groupKey, t.id)
            if t.slack_channel and t.slack_ts and settings.slack_bot_token:
                severity = related.labels(group).get("severity")
                text = related_text(group.title, match.matched, severity, match.louder)
                blocks = related_blocks(text, t.id, rid) if buttons else None
                await db["slack"].post(t.slack_channel, text, t.slack_ts, blocks)
            return {"status": "related", "investigation": t.id}

        t = Investigation(
            id=str(uuid.uuid4()),
            contract_id=contract_id,
            title=group.title,
            group_key=group.groupKey,
            started=started,
            input=group.model_dump(mode="json"),
        )
        await store().insert(t)
        await store().remember_group(contract_id, group.groupKey, started, t.id, seen | firing)
        if reason := await over_budget(contract_id):
            # Recorded and remembered, so repeats are duplicates, not one refusal each.
            await refuse(t, reason)
            return {"status": "refused", "investigation": t.id, "reason": reason}
        spawn(run(t, lambda a: agent.start(a, group, t.id)))
        return {"status": "accepted", "investigation": t.id}

    @app.post("/contracts/{contract_id}/grafana", status_code=202)
    async def grafana(
        contract_id: str,
        payload: GrafanaAlertGroup,
        creds: HTTPAuthorizationCredentials = Depends(bearer),  # noqa: B008
    ) -> dict[str, Any]:
        """Grafana Alerting's webhook contact point, with the Contract's webhook token as
        its Bearer credentials: from here on the same path as Alertmanager's."""
        return await alertmanager(contract_id, payload.normalized(), creds)

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

    async def console_decide(
        investigation_id: str, deadline: float, approve: bool, reason: str, login: str
    ) -> bool:
        """A console decision on one pause (the deadline its page showed)."""
        t = await store().get(investigation_id)
        if t is None or t.status != "awaiting_approval":
            return False
        who = f"{clean(login, 200)} in the console"
        if approve:
            message, note = "", f":white_check_mark: Approved by {who}."
        else:
            message = reason.strip() or "Rejected by the Operator. Do not retry."
            shown = f": {clean(reason.strip(), 2000)}" if reason.strip() else ""
            note = f":no_entry: Rejected by {who}{shown}"
        return await settle(t, deadline, approve, message, f"console:{login}", note)

    async def console_ask(contract_id: str, text: str, question_id: str | None) -> str | None:
        """A Question from the console, or a follow-up on question_id: the
        Investigation's id, or None when there's nothing to ask (still running, not
        a Question). The ask's time orders it like a Slack ts."""
        asked = f"{now():.6f}"
        if question_id is None:
            t = await start_question(contract_id, text, asked)
            return t.id if t else None
        t = await store().get(question_id)
        if t is None or not await follow_up(t, text, asked):  # the claim checks the kind
            return None
        return t.id

    async def health(c: contracts.Contract) -> list[dict[str, Any]]:
        """Each of a Contract's integrations, through its own tools: ok, how long, and
        on failure the error (redacted, capped). Never the data a check returns."""

        async def check(
            client: Client[Any], name: str, tool: str | None, args: Any
        ) -> dict[str, Any]:
            start, detail = time.monotonic(), ""
            try:
                if tool is None:  # a vendor: it starts, and offers every listed tool
                    offered = await asyncio.wait_for(client.list_tools(), PROBE_SECONDS)
                    missing = sorted(set(args["expect"]) - {t.name for t in offered})
                    detail = f"not offered: {', '.join(missing)}" if missing else ""
                else:
                    result = await asyncio.wait_for(
                        client.call_tool(tool, args, raise_on_error=False), PROBE_SECONDS
                    )
                    if result.is_error:
                        texts = (getattr(b, "text", "") for b in result.content)
                        detail = " ".join(texts) or "error"
            except Exception as e:  # a timeout, an unreachable cluster: it's the answer
                detail = f"{type(e).__name__}: {e}"
            ms = round(1000 * (time.monotonic() - start))
            return {"name": name, "ok": not detail, "ms": ms, "detail": redact_capped(detail, 300)}

        try:
            async with Client(mcp_factory(c).mcp) as client:
                return list(await asyncio.gather(*(check(client, *p) for p in agent.probes(c))))
        except Exception as e:  # the tools couldn't even be built (a bad kubeconfig)
            detail = redact_capped(f"{type(e).__name__}: {e}", 300)
            return [{"name": "tools", "ok": False, "ms": 0, "detail": detail}]

    async def console_file_jira(t: Investigation, login: str) -> tuple[str | None, str]:
        return await file_jira(t, f"console:{login}", login)

    if settings.console_operators:  # off by default: 404, not a login page
        app.include_router(
            console.router(
                settings.console_operators,
                by_id,
                store,
                console_decide,
                console_ask,
                health,
                shown_settings(settings),
                approver_token,
                console_file_jira,
                jira_of,
            )
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics(request: Request) -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app
