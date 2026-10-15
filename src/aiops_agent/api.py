"""Alertmanager webhook receiver for every Contract.

POST /contracts/{id}/alertmanager  That Contract's Alertmanager (its own webhook token).
                                Starts a triage, or makes a resolved group's
                                proposed actions stale. Unknown id = wrong token = 401.
GET  /triages[/{id}]            Status, report, pending actions (approver token).
POST /triages/{id}/decision     Approve or reject pending actions (approver token).
GET  /healthz, /metrics

ponytail: triage state, dedup and the LangGraph checkpointer live in memory, so
run a single replica. For HA, swap InMemorySaver for a Postgres checkpointer
and the dicts below for that same database.
"""

import asyncio
import logging
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from aiops_agent import agent, contracts
from aiops_agent.config import Settings
from aiops_agent.models import AlertGroup, TriageReport
from aiops_agent.observability import PENDING_APPROVALS, TRIAGE_SECONDS, TRIAGES

log = logging.getLogger("aiops.api")
DEDUP_SECONDS = 30 * 60


class Triage(BaseModel):
    id: str
    contract_id: str
    title: str
    group_key: str = ""
    group_resolved: bool = False
    status: Literal["running", "awaiting_approval", "done", "failed"] = "running"
    started: float
    report: TriageReport | None = None
    pending: list[dict[str, Any]] = []
    executed_actions: list[str] = []
    error: str | None = None


class Decision(BaseModel):
    approve: bool
    message: str = ""


def slack_text(t: Triage) -> str:
    if t.report:
        body = t.report.to_markdown(t.executed_actions).replace("**", "*").replace("## ", "*")
    elif t.pending:
        body = "Waiting for approval:\n" + "\n".join(f"- {p['description']}" for p in t.pending)
    else:
        body = f"Triage failed: {t.error}"
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
    model = model or agent.build_model(settings)
    if mcp_factory is None:
        mcp_factory = lambda c: agent.build_mcp(c, settings)  # noqa: E731
    checkpointer = InMemorySaver()
    triages: dict[str, Triage] = {}
    # (contract, group key) -> (start of its latest triage, that triage's id, every
    # fingerprint seen). Two Contracts can send the same group key.
    recent: dict[tuple[str, str], tuple[float, str, set[str]]] = {}
    slots = asyncio.Semaphore(settings.max_concurrent_triages)
    tasks: set[asyncio.Task[None]] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        yield
        for task in tasks:
            task.cancel()

    app = FastAPI(title="aiops-sre-agent", lifespan=lifespan)
    bearer = HTTPBearer()

    def check(creds: HTTPAuthorizationCredentials, expected: str) -> None:
        if not secrets.compare_digest(creds.credentials.encode(), expected.encode()):
            raise HTTPException(401, "invalid token")

    def approver_auth(creds: HTTPAuthorizationCredentials = Depends(bearer)) -> None:  # noqa: B008
        check(creds, approver_token)

    async def notify(t: Triage) -> None:
        log.info("triage %s %s", t.id, t.status)
        if not settings.slack_webhook_url:
            return
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                await http.post(
                    settings.slack_webhook_url.get_secret_value(), json={"text": slack_text(t)}
                )
        except httpx.HTTPError as e:
            log.warning("slack notification failed: %s", e)

    def apply(t: Triage, outcome: agent.Outcome) -> None:
        t.report, t.pending = outcome.report, outcome.pending
        t.executed_actions = outcome.executed_actions
        t.status = "done" if outcome.done else "awaiting_approval"

    async def run(t: Triage, step: Any) -> None:
        async with slots:
            try:
                # Always the Triage's own Contract, on start and on every resume.
                toolbox = mcp_factory(by_id[t.contract_id])
                async with agent.open_agent(settings, toolbox, model, checkpointer) as a:
                    apply(t, await step(a))
            except Exception as e:  # report every failure, never lose an alert silently
                log.exception("triage %s failed", t.id)
                t.status, t.error = "failed", f"{type(e).__name__}: {e}"
        if t.status == "awaiting_approval" and t.group_resolved:
            reject_stale(t, "The alert group resolved before a decision")
            return  # no one to ask; the resumed run reports
        PENDING_APPROVALS.set(sum(len(x.pending) for x in triages.values()))
        if t.status != "awaiting_approval":
            TRIAGES.labels(t.status).inc()
            TRIAGE_SECONDS.observe(time.time() - t.started)
        await notify(t)
        if t.status == "awaiting_approval":
            spawn(expire(t, t.pending))

    async def expire(t: Triage, pending: list[dict[str, Any]]) -> None:
        await asyncio.sleep(settings.decision_timeout_seconds)
        if t.pending is pending:  # still the same pause: nobody decided
            reject_stale(t, f"No decision within {settings.decision_timeout_seconds}s")

    def resume(t: Triage, decisions: list[dict[str, Any]]) -> None:
        t.status, t.pending = "running", []
        spawn(run(t, lambda a: agent.resume(a, t.id, decisions)))

    def reject_stale(t: Triage, reason: str) -> None:
        """A stale proposed action is rejected automatically; the triage still ends
        with a report."""
        if t.status != "awaiting_approval":
            return
        log.info("triage %s stale: %s, rejecting %s", t.id, reason, [p["name"] for p in t.pending])
        msg = f"{reason}. The action was not executed. Do not retry; finish the report."
        resume(t, [{"type": "reject", "message": msg} for _ in t.pending])

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
        key = (contract_id, group.groupKey)
        if not group.firing:
            same_group = [t for t in triages.values() if (t.contract_id, t.group_key) == key]
            for t in same_group:
                t.group_resolved = True  # still investigating: goes stale when it pauses
            stale = [t for t in same_group if t.status == "awaiting_approval"]
            for t in stale:
                reject_stale(t, "The alert group resolved before a decision")
            if stale:
                return {"status": "stale", "triages": [t.id for t in stale]}
            return {"status": "ignored", "reason": "no firing alerts"}
        firing = {a.fingerprint for a in group.firing}
        now = time.time()
        for k, (started, _, _) in list(recent.items()):
            if now - started > DEDUP_SECONDS:
                del recent[k]
        seen: set[str] = set()
        if key in recent:
            _, previous, seen = recent[key]
            # Alertmanager re-sends on every repeat_interval and when an Alert resolves.
            # Only an Alert not seen before is new work.
            if firing <= seen:
                return {"status": "duplicate", "triage": previous}

        t = Triage(
            id=str(uuid.uuid4()),
            contract_id=contract_id,
            title=group.title,
            group_key=group.groupKey,
            started=now,
        )
        triages[t.id] = t
        recent[key] = (now, t.id, seen | firing)
        spawn(run(t, lambda a: agent.start(a, group, t.id)))
        return {"status": "accepted", "triage": t.id}

    @app.get("/triages", dependencies=[Depends(approver_auth)])
    async def list_triages() -> list[Triage]:
        return sorted(triages.values(), key=lambda t: t.started, reverse=True)[:50]

    @app.get("/triages/{triage_id}", dependencies=[Depends(approver_auth)])
    async def get_triage(triage_id: str) -> Triage:
        if triage_id not in triages:
            raise HTTPException(404, "unknown triage")
        return triages[triage_id]

    @app.post(
        "/triages/{triage_id}/decision", status_code=202, dependencies=[Depends(approver_auth)]
    )
    async def decide(triage_id: str, decision: Decision) -> dict[str, str]:
        t = triages.get(triage_id)
        if t is None:
            raise HTTPException(404, "unknown triage")
        if t.status != "awaiting_approval":
            raise HTTPException(409, f"triage is {t.status}, nothing to decide")
        if decision.approve:
            decisions: list[dict[str, Any]] = [{"type": "approve"} for _ in t.pending]
        else:
            msg = decision.message or "Rejected by the on-call engineer. Do not retry."
            decisions = [{"type": "reject", "message": msg} for _ in t.pending]
        log.info(
            "triage %s decision approve=%s actions=%s",
            t.id,
            decision.approve,
            [p["name"] for p in t.pending],
        )
        resume(t, decisions)
        return {"status": "resumed"}

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics(request: Request) -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app
