# ruff: noqa: F811 - sock is test_slack's fixture, imported for these tests
"""Create Jira issue (slice 4.4b): the Operator files a finished Report into the
Contract's own Jira project, once, from Slack or the console. Jira Cloud and
Slack's Web API are fakes behind one httpx transport, as the Hub shares one client."""

import base64
import json
from typing import Any

import httpx
import pytest

from aiops_agent.models import Evidence, TriageReport
from aiops_agent.servers import jira
from tests.conftest import REPORT, call, make_contract, make_fake_cluster
from tests.test_api import ALERT, HOOK, URL, client
from tests.test_console import SAME, VIEW
from tests.test_restart import wait_for
from tests.test_slack import (  # noqa: F401 - _slack: the bot token and a database
    ACME,
    ACME_CLIENT,
    BANK,
    TOKEN,
    FakeSlack,
    FakeSocket,
    _slack,
    buttons,
    click,
    ephemerals,
    replies,
    sock,
    until,
)

JIRA = {
    "name": "jira",
    "url": "https://acme.atlassian.net",
    "email": "sre@acme.example",
    "token_secret": "jira-token",
    "project": "OPS",
    "issue_type": "Incident",
}
ACME_SECRET = {"jira-token": "acme-jira-token"}
BASIC = "Basic " + base64.b64encode(b"sre@acme.example:acme-jira-token").decode()
REPORT_STEP = call("TriageReport", "r", **REPORT)


class FakeJira:
    """Records creates; `answers` overrides the next ones (a Response, or an
    exception to raise, as a timeout would)."""

    def __init__(self) -> None:
        self.creates: list[httpx.Request] = []
        self.answers: list[Any] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.creates.append(request)
        if self.answers:
            answer = self.answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        project = json.loads(request.content)["fields"]["project"]["key"]
        return httpx.Response(201, json={"id": "1", "key": f"{project}-{len(self.creates)}"})


def transport(slack: FakeSlack, jira_: FakeJira) -> httpx.MockTransport:
    def route(request: httpx.Request) -> httpx.Response:
        return jira_(request) if request.url.host.endswith("atlassian.net") else slack(request)

    return httpx.MockTransport(route)


def done(settings: Any, fake_cluster: Any, slack: FakeSlack, jira_: FakeJira, **kw: Any) -> Any:
    settings.console_operators = {"alex@example.com"}
    return client(
        settings,
        fake_cluster,
        REPORT_STEP,
        slack=transport(slack, jira_),
        acme_channel=ACME,
        acme={"integrations": [{"name": "kubernetes"}, JIRA], "secrets": ACME_SECRET},
        **kw,
    )


def fields(request: httpx.Request) -> dict[str, Any]:
    return dict(json.loads(request.content)["fields"])


def texts(node: Any) -> list[str]:
    if isinstance(node, dict):
        own = [node["text"]] if node.get("type") == "text" else []
        return own + [t for child in node.get("content", []) for t in texts(child)]
    return []


def test_the_operator_files_the_report_once_from_slack(
    settings: Any, fake_cluster: Any, sock: FakeSocket
) -> None:
    slack, fake = FakeSlack(sock.url), FakeJira()
    with done(settings, fake_cluster, slack, fake, acme_client=ACME_CLIENT) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        until(lambda: "create_jira" in buttons(slack))
        both = buttons(slack)
        assert set(both) == {"send_to_client", "create_jira"}
        assert both["create_jira"]["confirm"]["text"]["text"].endswith("Jira project OPS.")
        sock.send(click("send_to_client", both["send_to_client"]["value"]))
        until(lambda: any("Sent to the client" in r for r in replies(slack)))
        assert set(buttons(slack)) == {"create_jira"}  # sending leaves Create Jira issue
        sock.send(click("create_jira", both["create_jira"]["value"]))
        sock.send(click("create_jira", both["create_jira"]["value"]))  # a double click
        until(lambda: any(":ticket: Filed as OPS-1" in r for r in replies(slack)))
        until(lambda: len(ephemerals(slack)) == 1)
        assert buttons(slack) == {}
        assert ":ticket: OPS-1" in slack.calls[-2][1]["text"]  # the parent, updated
        page = c.get(f"/console/investigations/{tid}", headers=VIEW).text
    (create,) = fake.creates
    assert create.headers["authorization"] == BASIC and TOKEN not in str(create.headers)
    f = fields(create)
    assert f["project"] == {"key": "OPS"} and f["issuetype"] == {"name": "Incident"}
    assert f["summary"] == REPORT["summary"] and f["labels"] == ["aiops"]
    body = texts(f["description"])
    assert REPORT["probable_root_cause"] in " ".join(body)
    assert "kubernetes_pod_logs: java.lang.OutOfMemoryError: Java heap space" in body
    assert f"Filed by aiops from Investigation {tid}." in body
    assert ephemerals(slack)[0][1] == "Already filed (or being filed), or nothing to file."
    assert "https://acme.atlassian.net/browse/OPS-1" in page and "slack:U0OPERATOR1" in page


def test_a_refusal_can_be_retried_and_no_answer_cannot(
    settings: Any, fake_cluster: Any, sock: FakeSocket
) -> None:
    """A 400 created nothing: free the claim. A timeout may have created it: keep the
    claim, so a second click never files a duplicate."""
    slack, fake = FakeSlack(sock.url), FakeJira()
    refusal = {"errorMessages": [], "errors": {"issuetype": "Specify a valid issue type"}}
    fake.answers = [httpx.Response(400, json=refusal), httpx.ReadTimeout("slow")]
    with done(settings, fake_cluster, slack, fake) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        until(lambda: "create_jira" in buttons(slack))
        value = buttons(slack)["create_jira"]["value"]
        sock.send(click("create_jira", value))
        until(lambda: len(ephemerals(slack)) == 1)
        sock.send(click("create_jira", value))  # retried: Jira times out
        until(lambda: len(ephemerals(slack)) == 2)
        sock.send(click("create_jira", value))  # outcome unknown: no new create
        until(lambda: len(ephemerals(slack)) == 3)
        page = c.get(f"/console/investigations/{tid}", headers=VIEW).text
    assert [e[1] for e in ephemerals(slack)] == [
        "Jira refused the issue (400 issuetype: Specify a valid issue type): nothing was created.",
        "Jira didn't answer (ReadTimeout): it may have created the issue. "
        "Check project OPS before filing it by hand.",
        "Already filed (or being filed), or nothing to file.",
    ]
    assert len(fake.creates) == 2
    assert "check project OPS before filing it by hand" in page


def test_the_console_files_it_and_the_slack_thread_shows_it(
    settings: Any, fake_cluster: Any, sock: FakeSocket
) -> None:
    slack, fake = FakeSlack(sock.url), FakeJira()
    with done(settings, fake_cluster, slack, fake) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        until(lambda: "create_jira" in buttons(slack))
        path = f"/console/investigations/{tid}/jira"
        assert c.post(path, headers=VIEW).status_code == 403  # no same-origin header
        assert "Create Jira issue" in c.get(f"/console/investigations/{tid}", headers=VIEW).text
        r = c.post(path, headers=SAME, follow_redirects=False)
        assert r.status_code == 303
        assert c.post(path, headers=SAME).status_code == 409  # filed already
        until(lambda: any("Filed as OPS-1 by alex@example.com" in x for x in replies(slack)))
        assert "create_jira" not in buttons(slack)
    assert len(fake.creates) == 1


def test_each_contract_files_into_its_own_project_with_its_own_token(
    settings: Any, fake_cluster: Any, sock: FakeSocket
) -> None:
    slack, fake = FakeSlack(sock.url), FakeJira()
    bank_jira = {**JIRA, "url": "https://bank.atlassian.net", "project": "BANK"}
    bank = make_contract(
        contract_id="bank",
        webhook_token="bank-token",
        slack_channel=BANK,
        integrations=[{"name": "kubernetes"}, bank_jira],
        secrets={"jira-token": "bank-jira-token"},
    )
    more = {"bank": (bank, make_fake_cluster())}
    steps = [REPORT_STEP, REPORT_STEP]
    with client(
        settings,
        fake_cluster,
        *steps,
        slack=transport(slack, fake),
        acme_channel=ACME,
        acme={"integrations": [{"name": "kubernetes"}, JIRA], "secrets": ACME_SECRET},
        more=more,
    ) as c:
        bank_id = c.post(
            "/contracts/bank/alertmanager",
            json=ALERT,
            headers={"Authorization": "Bearer bank-token"},
        ).json()["investigation"]
        wait_for(c, bank_id, "done")
        until(lambda: "create_jira" in buttons(slack))
        value = buttons(slack)["create_jira"]["value"]
        sock.send(click("create_jira", value, channel=ACME))  # bank's, clicked in acme's
        until(lambda: len(ephemerals(slack)) == 1)
        sock.send(click("create_jira", value, channel=BANK))
        until(lambda: any("Filed as BANK-" in r for r in replies(slack)))
    (create,) = fake.creates
    assert create.url.host == "bank.atlassian.net" and fields(create)["project"] == {"key": "BANK"}
    bank_basic = base64.b64encode(b"sre@acme.example:bank-jira-token").decode()
    assert create.headers["authorization"] == f"Basic {bank_basic}"


def test_the_issue_body_is_plain_text_and_only_kept_links_are_links() -> None:
    """Model text came from tool output: Jira markup in it must stay text."""
    report = TriageReport(
        **{
            **REPORT,
            "summary": "checkout is down\nsecond line [x|https://evil.example]",
            "evidence": [
                Evidence(
                    source="logs",
                    finding="see [click|https://evil.example] token=abcdefghij1234567890",
                ),
                Evidence(source="grafana_generate_deeplink", finding="explore", link="https://g/x"),
            ],
        }
    )
    doc = jira.report_document(report, ["kubernetes_evict_pod {}: ok"], "t1")
    marks = json.dumps(doc).count('"marks"')
    assert marks == 1 and '"href": "https://g/x"' in json.dumps(doc)
    body = texts(doc)
    assert "logs: see [click|https://evil.example] token=[REDACTED]" in body
    assert "kubernetes_evict_pod {}: ok" in body
    summary = jira.issue_summary(report)
    assert "\n" not in summary and len(summary) <= 255
    long = TriageReport(**{**REPORT, "summary": "x" * 600})
    assert len(jira.issue_summary(long)) <= 255


@pytest.mark.parametrize("agent_tools", [None])
def test_creating_is_never_an_agent_tool(agent_tools: Any) -> None:
    assert set(jira.ACCESS) == {"search_issues", "get_issue"}


@pytest.mark.parametrize(
    "answer,retried",
    [
        (httpx.ConnectError("no route"), True),  # nothing was sent: retry is safe
        (httpx.Response(504, text="Gateway Timeout"), False),  # may have been created
        (httpx.Response(201, json={"key": "<!channel>"}), False),  # created, key unusable
        (httpx.Response(201, json={"key": "BANK-9"}), False),  # not this project's key
    ],
)
def test_a_retry_is_allowed_only_when_nothing_can_have_been_created(
    settings: Any, fake_cluster: Any, sock: FakeSocket, answer: Any, retried: bool
) -> None:
    slack, fake = FakeSlack(sock.url), FakeJira()
    fake.answers = [answer]
    with done(settings, fake_cluster, slack, fake) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        path = f"/console/investigations/{tid}/jira"
        first = c.post(path, headers=SAME)
        second = c.post(path, headers=SAME, follow_redirects=False)
        t = c.get(f"/investigations/{tid}", headers={"Authorization": "Bearer approver-token"})
    assert first.status_code == 409
    assert len(fake.creates) == (2 if retried else 1)
    assert second.status_code == (303 if retried else 409)
    assert t.json()["jira_issue"] == ("OPS-2" if retried else None)
    assert not any("<!channel>" in r or "BANK-9" in r for r in replies(slack))


def test_an_empty_section_is_left_out() -> None:
    """ADF refuses a list with no items or an empty text: Jira would refuse every retry."""
    report = TriageReport(**{**REPORT, "recommended_actions": [], "summary": ""})
    doc = jira.report_document(report, [], "t1")
    kinds = [b["type"] for b in doc["content"]]
    assert "orderedList" not in kinds and "Recommendations" not in texts(doc)
    assert all(t for t in texts(doc))
