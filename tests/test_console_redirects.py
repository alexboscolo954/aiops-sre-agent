"""The Jinja console's old addresses (slice 11.7b): an Investigation's page goes to its
app page, anything else to the app; nothing is posted any more, and a Hub without
the console still has none."""

from typing import Any

from pydantic import SecretStr

from squero.config import Settings
from tests.test_api import client

OPERATOR = "alex@example.com"


def moved(settings: Settings, fake_cluster: Any, database_url: str) -> dict[str, Any]:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    paths = [
        "/console",
        "/console/health",
        "/console/teachings?contract=acme",
        "/console/investigations/abc",
        "/console/investigations/abc/scenario.yaml",
        "/console/investigations/a%26view%3Dtoken%23x",  # stays inside the id
        "/console/investigations/",
    ]
    with client(settings, fake_cluster) as c:
        got: dict[str, Any] = {p: c.get(p, follow_redirects=False) for p in paths}
        got["post"] = c.post("/console/questions", data={"question": "x"})
    return got


def test_old_console_addresses_redirect_into_the_app(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    got = moved(settings, fake_cluster, database_url)
    where = {p: (r.status_code, r.headers.get("location")) for p, r in got.items() if p != "post"}
    assert where == {
        "/console": (303, "/app/"),
        "/console/health": (303, "/app/"),
        "/console/teachings?contract=acme": (303, "/app/"),
        "/console/investigations/abc": (303, "/app/?view=investigation&id=abc"),
        "/console/investigations/abc/scenario.yaml": (303, "/app/?view=investigation&id=abc"),
        "/console/investigations/a%26view%3Dtoken%23x": (
            303,
            "/app/?view=investigation&id=a%26view%3Dtoken%23x",
        ),
        "/console/investigations/": (303, "/app/"),
    }
    assert got["post"].status_code == 405  # an old form changes nothing


def test_a_hub_without_the_console_has_no_old_addresses(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    settings.database_url = SecretStr(database_url)
    settings.console_operators = set()
    with client(settings, fake_cluster) as c:
        r = c.get("/console/investigations/abc", follow_redirects=False)
    assert r.status_code == 404
