"""Masking (slice 6.4): a Contract's identifiers never reach the LLM, and what comes
back holds them again. Secrets are redacted on the wire for every Contract."""

import json
from typing import Any

import httpx
import pytest
from fastmcp import FastMCP
from langchain_core.messages import BaseMessage
from mcp.types import ToolAnnotations
from pydantic import Field, SecretStr

from aiops_agent import agent, contracts, embeddings, masking, teachings
from aiops_agent.config import Settings
from aiops_agent.models import AlertGroup
from tests.conftest import REPORT, ScriptedModel, call, make_contract

KEY = "k-acme"
HOST, EMAIL, IP, NAME = "db1.acme.internal", "oncall@globex.com", "10.1.2.3", "Globex"
SECRET = "token: s3cr3tvalue123"
PLAIN = [HOST, "acme.internal", EMAIL, IP, NAME.lower(), "s3cr3tvalue123"]


def masker(key: str = KEY, **policy: Any) -> masking.Masker:
    return masking.Masker(key.encode(), policy.pop("terms", ["acme.internal", NAME]), **policy)


# --- what is masked ------------------------------------------------------------------


def test_terms_are_whole_words_in_any_case_and_a_domain_covers_its_subdomains() -> None:
    m, seen = masker(), masking.Seen()
    out = m.mask(
        "globex runs db1.ACME.internal and acme.internal; globexx and notacme.internal", seen
    )
    assert "globexx" in out and "notacme.internal" in out  # not whole words: kept
    assert "db1.ACME" not in out and "acme.internal;" not in out
    assert out.startswith(m.placeholder("name", "globex"))
    assert m.placeholder("host", HOST) in out  # the case doesn't change the placeholder
    assert set(seen.values()) == {"globex", "db1.ACME.internal", "acme.internal"}


def test_the_longest_term_wins_and_a_term_inside_a_word_is_kept() -> None:
    m, seen = masker(terms=[NAME, f"{NAME} Bank"]), masking.Seen()
    assert m.mask(f"{NAME} Bank", seen) == m.placeholder("name", f"{NAME} Bank")
    assert m.mask(f"x{NAME}", {}) == f"x{NAME}"


def test_a_value_written_twice_comes_back_as_first_written() -> None:
    m, seen = masker(), masking.Seen()
    out = m.mask("Globex then GLOBEX", seen)
    assert masking.unmask(out, seen) == "Globex then Globex"


def test_a_messages_raw_provider_fields_are_masked() -> None:
    from langchain.messages import AIMessage

    raw = {"tool_calls": [{"function": {"arguments": json.dumps({"host": HOST})}}]}
    seen = masking.Seen()
    m = masking._message(
        AIMessage(content="", additional_kwargs=raw), lambda s: masker().mask(s, seen)
    )
    assert HOST not in json.dumps(m.additional_kwargs) and seen


def test_emails_and_ips_are_masked_but_not_times_versions_or_loopback() -> None:
    m = masker(terms=[])
    out = m.mask(f"mail {EMAIL} from {IP} and fe80::1:2 at 12:30:45 v1.2.3 127.0.0.1 ::1", {})
    for kept in ("12:30:45", "v1.2.3", "127.0.0.1", "::1"):
        assert kept in out
    for gone in (EMAIL, IP, "fe80::1:2"):
        assert gone not in out
    assert m.placeholder("email", EMAIL) in out and m.placeholder("ip", IP) in out
    assert m.mask("999.1.1.1", {}) == "999.1.1.1"  # not an address


def test_each_shape_can_be_turned_off() -> None:
    m = masker(terms=[], emails=False, ips=True)
    assert EMAIL in m.mask(EMAIL, {}) and IP not in m.mask(IP, {})
    m = masker(terms=[], emails=True, ips=False)
    assert IP in m.mask(IP, {}) and EMAIL not in m.mask(EMAIL, {})


def test_an_email_under_a_listed_domain_is_one_email() -> None:
    m = masker(terms=["globex.com"])
    assert m.mask(EMAIL, {}) == m.placeholder("email", EMAIL)


def test_placeholders_are_stable_per_key_and_differ_across_keys() -> None:
    assert masker().placeholder("host", HOST) == masker().placeholder("host", HOST)
    assert masker().placeholder("host", HOST) != masker("k-bank").placeholder("host", HOST)


def test_unmask_restores_what_was_masked_and_leaves_inventions() -> None:
    m, seen = masker(), masking.Seen()
    text = f"{NAME} {HOST} {EMAIL}"
    out = m.mask(text, seen)
    assert masking.unmask(out, seen) == text
    bare = m.placeholder("host", HOST).strip("<>")  # copied without its brackets
    assert masking.unmask(f"see {bare}", seen) == f"see {HOST}"
    assert masking.unmask("<host-00000000>", seen) == "<host-00000000>"


def test_outgoing_redacts_secrets_without_a_mask() -> None:
    assert masking.outgoing(None, f"{HOST} {SECRET}") == f"{HOST} token: [REDACTED]"
    out = masking.outgoing(masker(), f"{HOST} {SECRET}")
    assert HOST not in out and "s3cr3tvalue123" not in out


# --- the Contract --------------------------------------------------------------------


def policy(**mask: Any) -> dict[str, Any]:
    return {"data_policy": {"mask": {"terms": ["acme.internal"], **mask}}}


def test_a_mask_needs_something_to_mask_and_the_contracts_key() -> None:
    with pytest.raises(ValueError, match="masks nothing"):
        make_contract(**policy(terms=[], emails=False, ips=False))
    with pytest.raises(ValueError, match="at least 3"):
        make_contract(**policy(terms=["ac"]))
    c = make_contract(**policy())
    assert contracts.MASK_KEY in c.secret_refs()  # load() refuses it missing
    assert contracts.MASK_KEY not in make_contract().secret_refs()
    assert masking.for_contract(make_contract()) is None


def masked_contract(contract_id: str = "acme", key: str = KEY) -> contracts.Contract:
    return make_contract(
        contract_id=contract_id,
        secrets={contracts.MASK_KEY: key},
        **policy(terms=["acme.internal", NAME]),
    )


def test_the_embedder_and_a_scenario_get_the_contracts_mask(settings: Settings) -> None:
    from aiops_agent import evals

    data = masked_contract().model_dump()
    data["integrations"].append({"name": "incidents"})
    c = contracts.build(data, secrets={contracts.MASK_KEY: SecretStr(KEY)})
    s = settings.model_copy(update={"embedding_model": "e", "model_base_url": "http://gw"})
    e = embeddings.for_contract(s, object(), c)  # type: ignore[arg-type]
    assert e is not None and e.masker is not None
    plain = evals.scenario_contract("shop", False, [], integrations=["kubernetes"])
    masked = evals.scenario_contract(
        "shop", False, [], integrations=["kubernetes"], data_policy={"mask": {"terms": [NAME]}}
    )
    assert masking.for_contract(plain) is None and masking.for_contract(masked) is not None


@pytest.mark.anyio
async def test_an_eval_masks_what_its_scenario_says(
    settings: Settings, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    from aiops_agent import evals

    model = recording(call("TriageReport", "c1", **REPORT))
    monkeypatch.setattr(agent, "build_model", lambda _s: model)
    scenario = {
        "namespace": "shop",
        "integrations": ["kubernetes"],
        "data_policy": {"mask": {"terms": ["acme.internal", NAME]}},
        "alert": ALERT.model_dump(mode="json"),
        "expect": {"category": ["resource_limits"]},
        "tools": {},
    }
    (tmp_path / "masked.yaml").write_text(yaml.safe_dump(scenario))
    await evals.run(tmp_path, settings, [])
    assert leaks(model) == []


def test_two_contracts_mask_the_same_host_differently() -> None:
    shop = masking.for_contract(masked_contract("acme", "k-acme"))
    bank = masking.for_contract(masked_contract("bank", "k-bank"))
    assert shop and bank
    assert shop.mask(HOST, {}) != bank.mask(HOST, {})


# --- the wire: every model call ------------------------------------------------------


class Recording(ScriptedModel):
    """A scripted model that keeps everything it was sent: messages and tools."""

    sent: list[str] = Field(default_factory=list)

    def bind_tools(self, tools: Any, **kwargs: Any) -> "Recording":
        specs = [t if isinstance(t, dict) else {"d": t.description, "a": t.args} for t in tools]
        self.sent.append(json.dumps(specs, default=str))
        return self

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        self.sent.append(json.dumps([m.model_dump() for m in messages], default=str))
        return super()._generate(messages, *args, **kwargs)


def recording(*steps: Any) -> Recording:
    return Recording(messages=iter(steps), sent=[])


def leaks(model: Recording) -> list[str]:
    sent = "\n".join(model.sent).lower()
    return [p for p in PLAIN if p.lower() in sent]


ALERT = AlertGroup.model_validate(
    {
        "status": "firing",
        "commonLabels": {"alertname": "DatabaseDown", "instance": HOST},
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "DatabaseDown", "instance": HOST},
                "annotations": {"summary": f"{NAME} payments down: page {EMAIL}; {SECRET}"},
            }
        ],
    }
)


def looking() -> tuple[agent.Toolbox, list[str]]:
    asked: list[str] = []
    mcp = FastMCP("t")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def look(host: str) -> str:
        """Look up a host under acme.internal."""
        asked.append(host)
        return f"{host} answered from {IP}"

    return agent.Toolbox(mcp, {"look": "read"}), asked


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["triage", "question", "check"])
async def test_no_identifier_or_secret_reaches_the_model_and_the_result_has_them(
    settings: Settings, kind: agent.Kind
) -> None:
    c = masked_contract()
    m = masking.for_contract(c)
    assert m is not None
    host = m.placeholder("host", HOST)
    report = {**REPORT, "summary": f"{host} is down", "affected": [host]}
    final = {
        "triage": call("TriageReport", "c2", **report),
        "question": call(
            "Answer", "c2", answer=f"{host} is up", evidence=[{"source": "look", "finding": host}]
        ),
        "check": call(
            "CheckResult",
            "c2",
            passed=False,
            summary=f"{host} failed",
            evidence=[{"source": "look", "finding": host}],
            report=report,
        ),
    }[kind]
    model = recording(call("look", "c1", host=host), final)
    toolbox, asked = looking()
    raw: list[tuple[str, Any, str]] = []
    sent: list[str] = []

    async def record(tool: str, args: Any, result: str, error: bool) -> None:
        raw.append((tool, args, result))

    async def masked(placeholders: list[str]) -> None:
        sent.extend(placeholders)

    async with agent.open_agent(
        settings,
        toolbox,
        model,
        record=record,
        kind=kind,
        taught=f"Teachings: {HOST} is the primary.",  # the system prompt
        masker=m,
        masked=masked,
    ) as a:
        if kind == "triage":
            outcome = await agent.start(a, ALERT, "t1")
        elif kind == "question":
            outcome = await agent.ask(a, f"Is {HOST} up? Ask {EMAIL}. {SECRET}", "t1")
        else:
            outcome = await agent.check(a, "db", f"{HOST} answers; {NAME} is fine", "t1")
    assert leaks(model) == []
    assert asked == [HOST]  # the tool ran on the real name
    assert raw == [("look", {"host": HOST}, f"{HOST} answered from {IP}")]  # stored plaintext
    assert outcome.call_log[0]["args"] == {"host": HOST}
    if kind == "question":
        assert outcome.answer and outcome.answer.answer == f"{HOST} is up"
    else:
        assert outcome.report and outcome.report.summary == f"{HOST} is down"
        assert outcome.report.affected == [HOST]
    assert host in sent and m.placeholder("ip", IP) in sent
    assert any(host in s for s in model.sent)  # the model did see the placeholder
    assert "copy each\\none whole" in model.sent[1]  # the system prompt says how to use them


@pytest.mark.anyio
async def test_without_a_mask_names_go_as_they_are_and_secrets_never(settings: Settings) -> None:
    model = recording(call("TriageReport", "c1", **REPORT))
    toolbox, _ = looking()
    async with agent.open_agent(settings, toolbox, model) as a:
        await agent.start(a, ALERT, "t1")
    sent = "".join(model.sent)
    assert "s3cr3tvalue123" not in sent  # redacted for every Contract
    assert HOST in sent and EMAIL in sent  # no Data policy, no masking
    assert "Masked values" not in sent


@pytest.mark.anyio
async def test_the_teaching_drafter_is_masked_too(settings: Settings) -> None:
    m = masking.for_contract(masked_contract())
    assert m is not None
    host = m.placeholder("host", HOST)
    model = recording(call("TeachingDraft", "c1", text=f"Check {host} first"))
    d = await teachings.draft(model, settings, f"{HOST} was down", f"ask {EMAIL}", [], masker=m)
    assert d.text == f"Check {HOST} first"
    assert leaks(model) == []


@pytest.mark.anyio
async def test_embeddings_send_the_masked_text(settings: Settings) -> None:
    bodies: list[dict[str, Any]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        vector = [0.0] * embeddings.DIMENSIONS
        return httpx.Response(200, json={"data": [{"embedding": vector}], "usage": {}})

    s = settings.model_copy(
        update={
            "embedding_model": "e",
            "model_base_url": "http://gw",
            "model_api_key": SecretStr("x"),
        }
    )
    m = masking.for_contract(masked_contract())
    e = embeddings.Embedder(s, None, "acme", httpx.MockTransport(answer), masker=m)  # type: ignore[arg-type]
    await e.vector(f"{HOST} down, {EMAIL}, {SECRET}")
    (body,) = bodies
    assert all(p.lower() not in body["input"].lower() for p in PLAIN)
    assert m and m.placeholder("host", HOST) in body["input"]


# --- the Hub -------------------------------------------------------------------------


def test_the_console_counts_what_an_investigation_masked(
    settings: Settings, fake_cluster: Any, database_url: str
) -> None:
    from tests.test_api import ALERT as HUB_ALERT
    from tests.test_api import HOOK, URL, client
    from tests.test_console import OPERATOR, VIEW
    from tests.test_restart import wait_for

    settings.database_url = SecretStr(database_url)
    settings.console_operators = {OPERATOR}
    acme = {
        "data_policy": {"mask": {"terms": ["checkout"]}},  # the alert's pod checkout-7d9f-abc
        "secrets": {contracts.MASK_KEY: KEY},
    }
    with client(settings, fake_cluster, call("TriageReport", "c1", **REPORT), acme=acme) as c:
        tid = c.post(URL, json=HUB_ALERT, headers=HOOK).json()["investigation"]
        wait_for(c, tid, "done")
        page = c.get(f"/console/investigations/{tid}", headers=VIEW).text
        plain = c.get("/console", headers=VIEW).text
    assert "Masked for the LLM: 1 name<" in page
    assert "Masked for the LLM" not in plain
