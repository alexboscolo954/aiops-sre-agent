"""Alertmanager webhook receiver for every Contract.

POST /contracts/{id}/alertmanager  That Contract's Alertmanager (its own webhook token).
                                Starts a triage, or makes a resolved group's
                                proposed actions stale. Unknown id = wrong token = 401.
GET  /investigations[/{id}]     Status, report, pending actions (approver token).
POST /investigations/{id}/decisionApprove or reject pending actions (approver token).
GET  /healthz, /metrics

State lives in Postgres (store.py): Investigations, the dedup memory, every
Approval decision and the LangGraph checkpoints, so a pending approval survives a
restart. ponytail: timers and the concurrency limit are per process, so run one
replica; several would each re-arm the same deadlines (harmless: claims are
atomic) but share no limit.
"""

import asyncio
import logging
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
from aiops_agent.store import Store, connect, now

log = logging.getLogger("aiops.api")
DEDUP_SECONDS = 30 * 60


class Decision(BaseModel):
    approve: bool
    message: str = ""


def slack_text(t: Investigation) -> str:
    if t.report:
        body = t.report.to_markdown(t.executed_actions).replace("**", "*").replace("## ", "*")
    elif t.pending:
        body = "Waiting for approval:\n" + "\n".join(f"- {p['description']}" for p in t.pending)
    else:
        body = f"Investigation failed: {t.error}"
    return f"*[aiops] [{t.contract_id}] {t.title}* (`{t.id}`)\n{body}"


def create_app(
    settings: Settings | None = None,
    model: BaseChatModel | None = None,
    mcp_factory: Any = None,
    by_id: dict[str, contracts.Contract] | None = None,
) -> FastAPI:
    """mcp_factory(contract) -> Toolbox, and by_id (the loaded Contracts), for tests."""
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
        async with connect(database_url) as pool:
            db["store"] = Store(pool)
            await store().migrate()
            db["checkpointer"] = AsyncPostgresSaver(pool)
            await db["checkpointer"].setup()
            await recover()
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
        if not settings.slack_webhook_url:
            return
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                await http.post(
                    settings.slack_webhook_url.get_secret_value(), json={"text": slack_text(t)}
                )
        except httpx.HTTPError as e:
            log.warning("slack notification failed: %s", e)

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

    async def run(t: Investigation, step: Any) -> None:
        async with slots:
            try:
                # Always the Investigation's own Contract, on start and on every resume.
                toolbox = mcp_factory(by_id[t.contract_id])
                async with agent.open_agent(settings, toolbox, model, db["checkpointer"]) as a:
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

    async def resume(t: Investigation, decisions: list[dict[str, Any]]) -> None:
        t.status, t.pending, t.deadline = "running", [], None
        spawn(run(t, lambda a: agent.resume(a, t.id, decisions)))

    async def reject_stale(investigation_id: str, deadline: float | None, reason: str) -> bool:
        """A stale proposed action is rejected automatically; the investigation still
        ends with a report. False when someone else already decided this pause."""
        pending = await store().claim(investigation_id, deadline)
        t = await store().get(investigation_id)
        if pending is None or t is None:
            return False
        log.info(
            "investigation %s stale: %s, rejecting %s", t.id, reason, [p["name"] for p in pending]
        )
        msg = f"{reason}. The action was not executed. Do not retry; finish the report."
        await store().record_decision(t.id, False, pending, msg, "stale")
        await resume(t, [{"type": "reject", "message": msg} for _ in pending])
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
        pending = await store().claim(t.id, t.deadline) if t.status == "awaiting_approval" else None
        if pending is None:  # already decided, stale, or never paused
            current = await store().get(t.id)
            status = current.status if current else t.status
            raise HTTPException(409, f"investigation is {status}, nothing to decide")
        if decision.approve:
            decisions: list[dict[str, Any]] = [{"type": "approve"} for _ in pending]
            message = ""
        else:
            message = decision.message or "Rejected by the Operator. Do not retry."
            decisions = [{"type": "reject", "message": message} for _ in pending]
        log.info(
            "investigation %s decision approve=%s actions=%s",
            t.id,
            decision.approve,
            [p["name"] for p in pending],
        )
        await store().record_decision(t.id, decision.approve, pending, message, "operator")
        await resume(t, decisions)
        return {"status": "resumed"}

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics(request: Request) -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app
