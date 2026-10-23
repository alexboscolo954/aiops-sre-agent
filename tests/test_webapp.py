"""The console app (slice 9.5a): the Jinja console's guards hold for /app/ and
/api/v1/ too (identity, approver cookie, CSP, text only), and a Contract's Sizings
never reach another's API."""

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from aiops_agent import webapp
from aiops_agent.config import Settings
from aiops_agent.store import Store, connect
from tests.conftest import make_contract
from tests.test_api import client
from tests.test_console import ACT, AS_OPERATOR, OPERATOR, VIEW
from tests.test_sizing_store import NOW, H, row, stored

ROOT = Path(__file__).parent.parent
PROM = {"name": "prometheus", "url": "http://prometheus"}
INTEGRATIONS = [{"name": "kubernetes"}, PROM]
CSP = "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'"


@pytest.fixture(autouse=True)
def _clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stored runs are at NOW: history's 14 and 400 days count back from it."""
    monkeypatch.setattr("aiops_agent.api.now", lambda: NOW)


@pytest.fixture
def app_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(
        '<!doctype html><script type="module" src="/app/assets/index-a1.js"></script>'
    )
    (tmp_path / "assets" / "index-a1.js").write_text("console.log(1)")
    (tmp_path / "assets" / "index-a1.css").write_text("body{}")
    (tmp_path / "secret.txt").write_text("not an asset")
    (tmp_path / "assets" / ".hidden").write_text("a dotfile is never served")
    monkeypatch.setattr(webapp, "APP_DIR", tmp_path)
    return tmp_path


def hub(settings: Settings, fake_cluster: Any, database_url: str) -> Any:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    bank = make_contract(contract_id="bank", integrations=INTEGRATIONS)
    return client(
        settings,
        fake_cluster,
        acme={"integrations": INTEGRATIONS},
        more={"bank": (bank, fake_cluster)},
    )


def seed(database_url: str, *runs: tuple[str, float, dict[str, Any]]) -> None:
    async def go() -> None:
        async with connect(database_url) as pool:
            store = Store(pool)
            await store.migrate()
            for cid, at, r in runs:
                await stored(store, cid, at, {"test": None}, r)

    asyncio.run(go())


# --- the doors ------------------------------------------------------------------------


def test_the_page_and_its_files_need_an_operators_identity(
    settings: Settings, fake_cluster: Any, database_url: str, app_dir: Path
) -> None:
    with hub(settings, fake_cluster, database_url) as c:
        page = c.get("/app/", headers=AS_OPERATOR)  # no token needed for the page
        js = c.get("/app/assets/index-a1.js", headers=AS_OPERATOR)
        css = c.get("/app/assets/index-a1.css", headers=AS_OPERATOR)
        refused = [
            c.get(path, headers=headers)
            for path in ("/app/", "/app/assets/index-a1.js")
            for headers in (ACT, {"Tailscale-User-Login": "mallory@example.com", **ACT})
        ]
        missing = [
            c.get(f"/app/assets/{name}", headers=AS_OPERATOR).status_code
            for name in ("nope.js", "..%2Fsecret.txt", ".hidden", "%2E%2E", "%2E%2E%2Fsecret.txt")
        ]
    assert page.status_code == 200 and "/app/assets/index-a1.js" in page.text
    assert page.headers["cache-control"] == "no-store"
    assert js.headers["content-type"].startswith("text/javascript")
    assert css.headers["content-type"].startswith("text/css")
    for r in (page, js, css):
        assert r.headers["content-security-policy"] == CSP
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["x-content-type-options"] == "nosniff"
    assert [r.status_code for r in refused] == [403] * 4
    assert set(missing) <= {404}


def test_the_api_also_needs_the_approver_cookie(
    settings: Settings, fake_cluster: Any, database_url: str, app_dir: Path
) -> None:
    with hub(settings, fake_cluster, database_url) as c:
        no_cookie = c.get("/api/v1/contracts", headers=AS_OPERATOR)
        bad_cookie = c.get(
            "/api/v1/contracts", headers={**AS_OPERATOR, "Cookie": "aiops_actions=x"}
        )
        stranger = c.get("/api/v1/contracts", headers=ACT)
        ok = c.get("/api/v1/contracts", headers=VIEW)
    for r in (no_cookie, bad_cookie):
        assert r.status_code == 401
        assert r.json()["detail"]["token_url"] == "/console/token"
    assert stranger.status_code == 403
    assert ok.status_code == 200 and ok.headers["content-security-policy"] == CSP
    assert ok.json() == [{"id": "acme", "name": "acme"}, {"id": "bank", "name": "bank"}]


def test_the_app_is_off_without_operators(
    settings: Settings, fake_cluster: Any, database_url: str, app_dir: Path
) -> None:
    settings.database_url = SecretStr(database_url)
    with client(settings, fake_cluster) as c:
        assert c.get("/app/", headers=VIEW).status_code == 404
        assert c.get("/api/v1/contracts", headers=VIEW).status_code == 404


def test_an_image_without_the_app_says_so(
    settings: Settings,
    fake_cluster: Any,
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(webapp, "APP_DIR", tmp_path / "none")
    with hub(settings, fake_cluster, database_url) as c:
        r = c.get("/app/", headers=AS_OPERATOR)
    assert r.status_code == 404 and "isn't built" in r.text


def test_the_jinja_console_links_the_app(
    settings: Settings, fake_cluster: Any, database_url: str, app_dir: Path
) -> None:
    with hub(settings, fake_cluster, database_url) as c:
        assert '<a href="/app/">Workloads</a>' in c.get("/console", headers=VIEW).text


# --- the data -------------------------------------------------------------------------


def test_workloads_are_the_latest_runs_ranked(
    settings: Settings, fake_cluster: Any, database_url: str, app_dir: Path
) -> None:
    seed(
        database_url,
        ("acme", NOW, row("api", waste={"cpu": 2.0, "memory": 0.0})),
        ("acme", NOW + H, row("api", waste={"cpu": 0.5, "memory": 0.0})),
        ("acme", NOW + 2 * H, row("web", waste={"cpu": 1.0, "memory": 0.0})),
    )
    seed(
        database_url,
        ("acme", NOW + 3 * H, row("api", waste={"cpu": 0.5, "memory": 0.0}, risks=[RISK])),
    )
    with hub(settings, fake_cluster, database_url) as c:
        body = c.get("/api/v1/contracts/acme/workloads", headers=VIEW).json()
        unknown = c.get("/api/v1/contracts/nope/workloads", headers=VIEW)
    assert body["contract"] == "acme"
    assert [w["workload"] for w in body["workloads"]] == ["test/shop/Deployment/api"]
    (api,) = body["workloads"]
    assert api["risks"] == [{**RISK, "container": "app"}]
    assert api["containers"][0]["cpu"] is None and api["waste"]["cpu"] == 0.5
    assert body["clusters"]["test"]["at"] == NOW + 3 * H
    assert unknown.status_code == 404


RISK = {"kind": "oom_killed", "text": "<img src=x onerror=alert(1)>"}


def test_history_is_hourly_for_14_days_and_daily_for_400(
    settings: Settings, fake_cluster: Any, database_url: str, app_dir: Path
) -> None:
    day = 86400.0
    times = [NOW - 20 * day + h * H for h in (1, 5)] + [NOW - day + h * H for h in (1, 2)]
    seed(database_url, *[("acme", at, row(pods=float(i))) for i, at in enumerate(times)])
    with hub(settings, fake_cluster, database_url) as c:
        q = "cluster=test&namespace=shop&kind=Deployment&name=api&container=app"
        recent = c.get(f"/api/v1/contracts/acme/history?{q}", headers=VIEW)
        year = c.get(f"/api/v1/contracts/acme/history?{q}&days=400", headers=VIEW)
        week = c.get(f"/api/v1/contracts/acme/history?{q}&days=7", headers=VIEW)
        other = c.get(f"/api/v1/contracts/bank/history?{q}", headers=VIEW)
    assert [p["pods"] for p in recent.json()["points"]] == [2.0, 3.0]
    assert [p["pods"] for p in year.json()["points"]] == [1.0, 3.0]  # the last of each day
    assert week.status_code == 422
    assert other.json() == {"points": []}


def test_a_contracts_sizings_never_reach_anothers_api(
    settings: Settings, fake_cluster: Any, database_url: str, app_dir: Path
) -> None:
    """Same cluster, namespace and Workload names in both Contracts."""
    seed(
        database_url,
        ("acme", NOW, row(policy="acme-only")),
        ("bank", NOW, row(policy="bank-only")),
    )
    q = "cluster=test&namespace=shop&kind=Deployment&name=api&container=app&days=400"
    with hub(settings, fake_cluster, database_url) as c:
        for cid in ("acme", "bank"):
            body = c.get(f"/api/v1/contracts/{cid}/workloads", headers=VIEW).json()
            policies = {x["policy"] for w in body["workloads"] for x in w["containers"]}
            assert policies == {f"{cid}-only"}
            points = c.get(f"/api/v1/contracts/{cid}/history?{q}", headers=VIEW).json()["points"]
            assert len(points) == 1


# --- text only, typed ------------------------------------------------------------------

RAW_HTML = re.compile(
    r"dangerouslySetInnerHTML|innerHTML|outerHTML|insertAdjacentHTML|document\.write"
)


def test_the_apps_source_never_writes_raw_html() -> None:
    sources = [
        p
        for p in (ROOT / "console" / "src").rglob("*")
        if p.suffix in {".ts", ".tsx"} and not p.name.endswith(".test.tsx")
    ]
    assert sources, "no app source found"
    for p in sources:
        assert not RAW_HTML.search(p.read_text()), p


def test_the_committed_openapi_is_the_apis() -> None:
    committed = (ROOT / "console" / "openapi.json").read_text()
    assert committed == webapp.openapi(), "run `make console-types` and commit the result"


def test_the_openapi_has_no_page_routes() -> None:
    paths = json.loads(webapp.openapi())["paths"]
    assert all(p.startswith("/api/v1/") for p in paths)
