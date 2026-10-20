"""The web console: the Operator's view of every Contract.

Who: Tailscale's identity header. `tailscale serve` sets Tailscale-User-Login on
every request it proxies and strips any copy a client sends, so the header is only
as trustworthy as the port: the Hub listens on 127.0.0.1 behind `serve` (slice
0.5), but local processes and the other containers on the compose network could
still send it themselves. So the header alone opens only the token page: every
other page, and every action, also needs the approver token, pasted once per browser
and kept as an HMAC of it in a Secure, HttpOnly, SameSite=Strict cookie. Every POST
must come from the console's own pages (Sec-Fetch-Site or Origin): the identity
header is ambient, so a page elsewhere could otherwise make the browser post.
Off unless AIOPS_CONSOLE_OPERATORS lists who may sign in.
"""

import asyncio
import hashlib
import hmac
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader

from aiops_agent import evals
from aiops_agent.contracts import Contract, Jira
from aiops_agent.models import Investigation
from aiops_agent.safety import redact
from aiops_agent.store import Store, now
from aiops_agent.teachings import LIMIT as TEACHING_LIMIT
from aiops_agent.teachings import section

# Autoescape always: alert titles come from client Alertmanagers, Reports and
# Answers from a model that reads tool output. Never mark anything |safe.
TEMPLATES = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=True
)
TEMPLATES.filters["when"] = lambda t: (
    datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d %H:%M:%S UTC") if t else "-"
)
HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
    "X-Frame-Options": "DENY",
}
COOKIE = "aiops_actions"
COOKIE_DAYS = 30
# decide(investigation id, the pause's deadline, approve, reason, login) -> decided
Decide = Callable[[str, float, bool, str, str], Awaitable[bool]]
# ask(contract id, question, follow-up on this Question or None) -> its id, or None
Ask = Callable[[str, str, str | None], Awaitable[str | None]]
QUESTION_LIMIT = 4000
# health(contract) -> one {name, ok, ms, detail} per integration check
Health = Callable[[Contract], Awaitable[list[dict[str, Any]]]]
# (investigation, the Operator's login) -> (the issue key, or None and why)
FileJira = Callable[[Investigation, str], Awaitable[tuple[str | None, str]]]
# (a finished Triage, right, the correction when wrong, login)
Feedback = Callable[[Investigation, bool, str | None, str], Awaitable[None]]
# (a proposed Teaching's row, approve, the text the Operator submitted, login) -> decided
DecideTeaching = Callable[[dict[str, Any], bool, str | None, str], Awaitable[bool]]
CORRECTION_LIMIT = 2000


def action_key(approver_token: str) -> str:
    """What the cookie holds: proof of the token, never the token itself (a stolen
    cookie can't call the API)."""
    return hmac.new(approver_token.encode(), b"aiops-console", hashlib.sha256).hexdigest()


def same_origin(request: Request) -> bool:
    site = request.headers.get("Sec-Fetch-Site")
    if site is not None:
        return site == "same-origin"
    origin = request.headers.get("Origin")
    return origin is not None and urlsplit(origin).netloc == request.headers.get("Host")


async def form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode()
    return {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}


def router(
    operators: set[str],
    by_id: dict[str, Contract],
    store: Callable[[], Store],
    decide: Decide,
    ask: Ask,
    health: Health,
    hub_config: dict[str, Any],
    approver_token: str,
    file_jira: FileJira,
    jira_of: Callable[[Investigation], Jira | None],
    feedback: Feedback,
    decide_teaching: DecideTeaching,
) -> APIRouter:
    key = action_key(approver_token)

    def operator(request: Request) -> str:
        login = request.headers.get("Tailscale-User-Login", "").strip()
        if not login or login not in operators:
            raise HTTPException(403, "not an Operator (sign in through tailscale serve)")
        return login

    def can_act(request: Request) -> bool:
        return hmac.compare_digest(request.cookies.get(COOKIE, ""), key)

    def viewer(request: Request, login: str = Depends(operator)) -> str:
        if not can_act(request):
            raise HTTPException(303, headers={"Location": "/console/token"})
        return login

    def posting(request: Request, login: str = Depends(operator)) -> str:
        if not same_origin(request):
            raise HTTPException(403, "cross-site request refused")
        return login

    def acting(request: Request, login: str = Depends(posting)) -> str:
        return viewer(request, login)

    def question_text(f: dict[str, str]) -> str:
        text = f.get("question", "").strip()
        if not text or len(text) > QUESTION_LIMIT:
            raise HTTPException(400, f"ask a question of 1 to {QUESTION_LIMIT} characters")
        return text

    console = APIRouter(prefix="/console")

    def page(request: Request, template: str, status: int = 200, **context: Any) -> HTMLResponse:
        name = request.headers.get("Tailscale-User-Name") or context["login"]
        html = TEMPLATES.get_template(template).render(name=name, **context)
        return HTMLResponse(html, status_code=status, headers=HEADERS)

    @console.get("", response_class=HTMLResponse)
    async def index(
        request: Request,
        contract: str | None = None,
        login: str = Depends(viewer),
    ) -> HTMLResponse:
        shown = contract if contract in by_id else None
        at = now()
        return page(
            request,
            "index.html",
            login=login,
            contracts=sorted(by_id.values(), key=lambda c: c.id),
            spend={cid: await store().month_spend(cid, at) for cid in by_id},
            shown=shown,
            investigations=await store().recent(100, shown),
            checks=await store().check_schedules(shown),
        )

    @console.get("/investigations/{investigation_id}", response_class=HTMLResponse)
    async def investigation(
        request: Request,
        investigation_id: str,
        login: str = Depends(viewer),
    ) -> HTMLResponse:
        t = await store().get(investigation_id)
        if t is None:
            raise HTTPException(404, "unknown investigation")
        return page(
            request,
            "investigation.html",
            login=login,
            t=t,
            jira=jira_of(t),
            usage=await store().investigation_usage(t.id),
            tool_calls=await store().tool_calls(t.id),
            decisions=await store().decisions(t.id),
            related=await store().related(t.id),
            feedback=await store().feedback(t.id),
            taught=[x for x in await store().teachings(t.contract_id) if x["source_id"] == t.id],
        )

    @console.get("/investigations/{investigation_id}/scenario.yaml")
    async def scenario(investigation_id: str, login: str = Depends(viewer)) -> Response:
        """A download only: the Hub never writes to the contracts repo."""
        t = await store().get(investigation_id)
        if t is None:
            raise HTTPException(404, "unknown investigation")
        if t.status != "done":
            raise HTTPException(409, f"investigation is {t.status}: only a finished one saves")
        if t.input is None or t.contract_id not in by_id:
            raise HTTPException(
                409, "started before Scenarios were recorded, or its Contract is gone"
            )
        body = evals.scenario_yaml(
            t,
            by_id[t.contract_id],
            await store().tool_calls(t.id),
            await store().decisions(t.id),
            await store().teachings(t.contract_id, "approved"),
        )
        name = f"{t.contract_id}-{t.id[:8]}.yaml"
        return Response(
            body,
            media_type="application/yaml",
            headers={**HEADERS, "Content-Disposition": f'attachment; filename="{name}"'},
        )

    @console.post("/investigations/{investigation_id}/decision")
    async def decision(
        request: Request,
        investigation_id: str,
        login: str = Depends(acting),
    ) -> RedirectResponse:
        f = await form(request)
        try:
            deadline = float(f["deadline"])
        except (KeyError, ValueError):
            raise HTTPException(400, "which pause?") from None
        approve = f.get("approve") == "1"
        if not await decide(investigation_id, deadline, approve, f.get("reason", ""), login):
            raise HTTPException(409, "already decided or Stale: nothing to decide")
        return RedirectResponse(f"/console/investigations/{investigation_id}", 303)

    @console.post("/investigations/{investigation_id}/jira")
    async def jira_issue(investigation_id: str, login: str = Depends(acting)) -> RedirectResponse:
        t = await store().get(investigation_id)
        if t is None:
            raise HTTPException(404, "unknown investigation")
        key, message = await file_jira(t, login)
        if key is None:
            raise HTTPException(409, message)
        return RedirectResponse(f"/console/investigations/{investigation_id}", 303)

    @console.post("/questions")
    async def question(request: Request, login: str = Depends(acting)) -> RedirectResponse:
        f = await form(request)
        if f.get("contract") not in by_id:
            raise HTTPException(400, "which Contract?")
        asked = await ask(f["contract"], question_text(f), None)
        if asked is None:
            raise HTTPException(409, "could not start the Question")
        return RedirectResponse(f"/console/investigations/{asked}", 303)

    @console.post("/investigations/{investigation_id}/questions")
    async def follow_up(
        request: Request, investigation_id: str, login: str = Depends(acting)
    ) -> RedirectResponse:
        t = await store().get(investigation_id)
        if t is None:
            raise HTTPException(404, "unknown investigation")
        if await ask(t.contract_id, question_text(await form(request)), t.id) is None:
            raise HTTPException(409, "still answering, or not a Question")
        return RedirectResponse(f"/console/investigations/{t.id}", 303)

    @console.post("/investigations/{investigation_id}/feedback")
    async def give_feedback(
        request: Request, investigation_id: str, login: str = Depends(acting)
    ) -> RedirectResponse:
        t = await store().get(investigation_id)
        if t is None:
            raise HTTPException(404, "unknown investigation")
        if not (t.kind in ("triage", "check") and t.status == "done" and t.report):
            raise HTTPException(409, "feedback is for a finished Report")
        f = await form(request)
        correct = f.get("correct") == "1"
        correction = f.get("correction", "").strip()
        if not correct and not 0 < len(correction) <= CORRECTION_LIMIT:
            raise HTTPException(400, f"say what was wrong, in 1 to {CORRECTION_LIMIT} characters")
        await feedback(t, correct, None if correct else correction, login)
        return RedirectResponse(f"/console/investigations/{t.id}", 303)

    @console.get("/teachings", response_class=HTMLResponse)
    async def teachings_page(
        request: Request, contract: str | None = None, login: str = Depends(viewer)
    ) -> HTMLResponse:
        shown = contract if contract in by_id else None
        rows = await store().teachings(shown)
        approved = [r for r in rows if r["status"] == "approved"]
        left = {
            cid: section([r for r in approved if r["contract_id"] == cid], None)[1] for cid in by_id
        }
        crowded = {cid: n for cid, n in sorted(left.items()) if n}
        return page(
            request,
            "teachings.html",
            login=login,
            contracts=sorted(by_id),
            shown=shown,
            proposed=[r for r in rows if r["status"] == "proposed"],
            approved=[r for r in rows if r["status"] == "approved"],
            past=[r for r in rows if r["status"] in ("rejected", "retired")],
            limit=TEACHING_LIMIT,
            crowded=crowded,
        )

    async def teaching_row(teaching_id: int) -> dict[str, Any]:
        row = await store().teaching(teaching_id)
        if row is None or row["contract_id"] not in by_id:
            raise HTTPException(404, "unknown Teaching")
        return row

    @console.post("/teachings/{teaching_id}/decision")
    async def teaching_decision(
        request: Request, teaching_id: int, login: str = Depends(acting)
    ) -> RedirectResponse:
        row = await teaching_row(teaching_id)
        f = await form(request)
        approve = f.get("approve") == "1"
        text = f.get("text", "").strip() if approve else None
        if approve and not 0 < len(text or "") <= TEACHING_LIMIT:
            raise HTTPException(400, f"a Teaching is 1 to {TEACHING_LIMIT} characters")
        if not await decide_teaching(row, approve, text, login):
            raise HTTPException(409, "already decided")
        return RedirectResponse(f"/console/teachings?contract={row['contract_id']}", 303)

    @console.post("/teachings/{teaching_id}/retire")
    async def retire(teaching_id: int, login: str = Depends(acting)) -> RedirectResponse:
        row = await teaching_row(teaching_id)
        if not await store().retire_teaching(row["id"], row["contract_id"], f"console:{login}"):
            raise HTTPException(409, "not an approved Teaching")
        return RedirectResponse(f"/console/teachings?contract={row['contract_id']}", 303)

    @console.post("/teachings")
    async def write_teaching(request: Request, login: str = Depends(acting)) -> RedirectResponse:
        """Written by the Operator: approved at once."""
        f = await form(request)
        if f.get("contract") not in by_id:
            raise HTTPException(400, "which Contract?")
        text = f.get("text", "").strip()
        if not 0 < len(text) <= TEACHING_LIMIT:
            raise HTTPException(400, f"a Teaching is 1 to {TEACHING_LIMIT} characters")
        alerts = [a.strip() for a in f.get("alerts", "").split(",") if a.strip()]
        await store().add_teaching(f["contract"], text, alerts, approved_by=f"console:{login}")
        return RedirectResponse(f"/console/teachings?contract={f['contract']}", 303)

    @console.get("/health", response_class=HTMLResponse)
    async def health_page(request: Request, login: str = Depends(viewer)) -> HTMLResponse:
        shown = sorted(by_id.values(), key=lambda c: c.id)
        checks = await asyncio.gather(*(health(c) for c in shown))
        last = await store().last_done()
        rows = [
            {
                "contract": c,
                "checks": check,
                "last": last.get(c.id),
                # The Contract as loaded, defaults included. Secret values never live
                # in the model: only their names, and whether each one decrypted.
                "config": yaml.safe_dump(c.model_dump(mode="json"), sort_keys=False),
                "secrets": {name: c.has_secret(name) for name in sorted(c.secret_refs())},
            }
            for c, check in zip(shown, checks, strict=True)
        ]
        hub = redact(yaml.safe_dump(hub_config, sort_keys=False))  # and redacted, to be sure
        return page(request, "health.html", login=login, rows=rows, hub=hub)

    @console.get("/token", response_class=HTMLResponse)
    async def token_form(request: Request, login: str = Depends(operator)) -> HTMLResponse:
        return page(request, "token.html", login=login, can_act=can_act(request))

    @console.post("/token")
    async def token(request: Request, login: str = Depends(posting)) -> RedirectResponse:
        given = (await form(request)).get("token", "")
        if not hmac.compare_digest(given.encode(), approver_token.encode()):
            raise HTTPException(403, "that is not the approver token")
        done = RedirectResponse("/console", 303)
        done.set_cookie(
            COOKIE,
            key,
            max_age=COOKIE_DAYS * 86400,
            path="/console",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return done

    return console
