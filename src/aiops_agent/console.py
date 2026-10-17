"""The web console: the Operator's view of every Contract.

Login is Tailscale's identity header. `tailscale serve` sets Tailscale-User-Login on
every request it proxies and strips any copy a client sends, so the header is only
as trustworthy as the port: nothing but `tailscale serve` may reach it. The Hub
listens on 127.0.0.1 behind it (slice 0.5), but local processes and the other
containers on the compose network can still connect and send the header themselves.
Off unless AIOPS_CONSOLE_OPERATORS lists who may sign in.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader

from aiops_agent.contracts import Contract

# Autoescape always: alert titles come from client Alertmanagers, Answers from a
# model that reads tool output. Never mark anything |safe.
TEMPLATES = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=True
)
HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
    "X-Frame-Options": "DENY",
}


def router(operators: set[str], by_id: dict[str, Contract]) -> APIRouter:
    def operator(request: Request) -> str:
        login = request.headers.get("Tailscale-User-Login", "").strip()
        if not login or login not in operators:
            raise HTTPException(403, "not an Operator (sign in through tailscale serve)")
        return login

    console = APIRouter(prefix="/console")

    def page(template: str, **context: object) -> HTMLResponse:
        return HTMLResponse(TEMPLATES.get_template(template).render(**context), headers=HEADERS)

    @console.get("", response_class=HTMLResponse)
    async def index(request: Request, login: str = Depends(operator)) -> HTMLResponse:
        name = request.headers.get("Tailscale-User-Name") or login
        contracts = sorted(by_id.values(), key=lambda c: c.id)
        return page("index.html", name=name, login=login, contracts=contracts)

    return console
