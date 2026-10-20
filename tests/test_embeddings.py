"""Similar incidents by meaning (slice 7.4): Report embeddings in pgvector, merged with
7.1's full-text search; one Contract's vectors never reach another's search."""

import json
import math
import time
from typing import Any

import httpx
import psycopg
import pytest
from fastmcp import Client
from pydantic import SecretStr, ValidationError

from aiops_agent import cli, contracts, embeddings
from aiops_agent.config import Price, Settings
from aiops_agent.servers import incidents
from aiops_agent.store import Store, connect, now
from tests.conftest import REPORT, call, make_contract
from tests.test_api import ALERT, HOOK, URL, client
from tests.test_api import wait_for as wait_status
from tests.test_incidents import past

pytestmark = pytest.mark.anyio
MODEL = "openai/text-embedding-3-small"
PRICE = Price(input=0.02, output=0)
TLS = "ingress certificate expired; cert-manager renewal failed"


def vec(i: int, j: int | None = None, tilt: float = 0.0) -> list[float]:
    """Unit vector e_i, tilted towards e_j: cosine distance 1 - cos(atan(tilt))."""
    v = [0.0] * embeddings.DIMENSIONS
    v[i] = 1.0
    if j is not None:
        v[j] = tilt
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


def hub(**kw: Any) -> Settings:
    base = {"model": "fake", "model_base_url": "http://gw/v1", "embedding_model": MODEL}
    return Settings(_env_file=None, **{**base, **kw})


class Fake(embeddings.Embedder):
    """Answers each text from `vectors` (by a word it contains) instead of the gateway."""

    def __init__(self, store: Store, vectors: dict[str, list[float]], **kw: Any) -> None:
        super().__init__(hub(model_prices={MODEL: PRICE}, **kw), store, "acme")
        self.vectors, self.texts = vectors, list[str]()

    async def vector(self, text: str) -> tuple[list[float], int]:
        self.texts.append(text)
        for word, v in self.vectors.items():
            if word in text:
                return v, 10
        raise httpx.ConnectError("gateway down")


@pytest.fixture
async def store(database_url: str) -> Any:
    async with connect(database_url) as pool:
        s = Store(pool)
        await s.migrate()
        yield s


async def search(store: Store, keywords: str, embedder: Any = None) -> list[str]:
    async with Client(incidents.build_server("acme", store, embedder)) as c:
        r = await c.call_tool("search", {"keywords": keywords})
        assert r.structured_content is not None
        return [i["id"] for i in r.structured_content["incidents"]]


async def embedded(store: Store, id_: str, v: list[float], model: str = MODEL) -> None:
    assert await store.set_embedding("acme", id_, model, v)


def usage(database_url: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(database_url) as conn:
        return conn.execute(
            "select investigation_id, contract_id, model, input_tokens, output_tokens, "
            "cost_usd from usage order by id"
        ).fetchall()


async def test_meaning_finds_a_past_report_its_words_miss(store: Store) -> None:
    """Done when: the alert's words share nothing with the past Report, its meaning does."""
    await store.insert(past("tls", TLS, "the ACME DNS challenge was blocked"))
    await embedded(store, "tls", vec(0))
    words = "web x509 handshake failure"
    assert await search(store, words) == []
    assert await search(store, words, Fake(store, {"x509": vec(0, 1, 0.5)})) == ["tls"]


async def test_only_close_vectors_by_the_same_model_count(store: Store) -> None:
    await store.insert(past("near", "a"))
    await store.insert(past("far", "b"))
    await store.insert(past("other-model", "c"))
    await embedded(store, "near", vec(0))
    await embedded(store, "far", vec(1))  # distance 1 to the query
    await embedded(store, "other-model", vec(0), model="another/embedder")
    found = await search(store, "zzz", Fake(store, {"zzz": vec(0, 1, 0.1)}))
    assert found == ["near"]
    tight = Fake(store, {"zzz": vec(0, 1, 1.0)}, embedding_max_distance=0.2)  # 0.29 away
    assert await search(store, "zzz", tight) == []


async def test_words_and_meaning_together_rank_first(store: Store) -> None:
    older = now() - 3 * 86400  # only the fused rank puts it first
    both = past("both", "checkout OOMKilled", "memory limit too low")
    await store.insert(both.model_copy(update={"started": older}))
    await store.insert(past("words", "checkout image pull failed"))
    await store.insert(past("meaning", "cart pods out of memory"))
    await embedded(store, "both", vec(0, 1, 0.2))
    await embedded(store, "meaning", vec(0, 1, 0.3))
    await embedded(store, "words", vec(2))
    found = await search(store, "checkout container killed", Fake(store, {"checkout": vec(0)}))
    # words: "words" (newer) then "both"; meaning: "both" then "meaning"; fused: both 1/62
    # + 1/61, words 1/61, meaning 1/62.
    assert found == ["both", "words", "meaning"]


async def test_a_failed_search_embedding_falls_back_to_words_and_costs_nothing(
    store: Store, database_url: str
) -> None:
    await store.insert(past("oom", "reports oomkilled"))
    assert await search(store, "reports oomkilled", Fake(store, {})) == ["oom"]
    assert usage(database_url) == []


async def test_a_search_embedding_is_the_contracts_usage(store: Store, database_url: str) -> None:
    await store.insert(past("oom", "reports oomkilled"))
    await search(store, "reports", Fake(store, {"reports": vec(0)}))
    assert usage(database_url) == [(None, "acme", MODEL, 10, 0, PRICE.cost(10, 0))]
    assert await store.month_spend("acme", now()) == pytest.approx(PRICE.cost(10, 0))


async def test_index_embeds_a_report_and_records_its_cost(store: Store, database_url: str) -> None:
    await store.insert(past("tls", TLS, "ACME challenge blocked"))
    row = await store.past_report("acme", "tls")
    fake = Fake(store, {"tls alert": vec(3)})
    assert await fake.index(row or {})
    assert "ACME challenge blocked" in fake.texts[0]
    assert usage(database_url) == [("tls", "acme", MODEL, 10, 0, PRICE.cost(10, 0))]
    assert await store.unembedded("acme", MODEL) == []
    assert [r["id"] for r in await store.unembedded("acme", "another/embedder")] == ["tls"]


async def test_a_failed_index_leaves_the_report_to_its_words(store: Store) -> None:
    await store.insert(past("tls", TLS))
    row = await store.past_report("acme", "tls")
    assert not await Fake(store, {}).index(row or {})
    assert [r["id"] for r in await store.unembedded("acme", MODEL)] == ["tls"]
    assert await search(store, "certificate") == ["tls"]


async def test_only_finished_triage_reports_wait_for_an_embedding(store: Store) -> None:
    await store.insert(past("ok", "a"))
    await store.insert(past("asked", "a", kind="question"))
    await store.insert(past("running", "a", status="running"))
    await store.insert(past("bank", "a", contract_id="bank"))
    assert [r["id"] for r in await store.unembedded("acme", MODEL)] == ["ok"]


def test_report_text_is_what_it_is_about_capped() -> None:
    report = {**REPORT, "probable_root_cause": "batch size unset"}
    text = embeddings.report_text("ReportsOOM", report)
    assert text.startswith("ReportsOOM\n") and "batch size unset" in text
    assert REPORT["evidence"][0]["finding"] in text
    assert len(embeddings.report_text("x" * 9000, report)) == embeddings.MAX_CHARS


async def test_the_gateway_call(store: Store) -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        size = 3 if b"short" in request.content else embeddings.DIMENSIONS
        data = [{"embedding": [0.5] * size}]
        return httpx.Response(200, json={"data": data, "usage": {"prompt_tokens": 7}})

    settings = hub(model_api_key=SecretStr("k"), model_headers={"X-Title": "aiops"})
    e = embeddings.Embedder(settings, store, "acme", httpx.MockTransport(answer))
    v, tokens = await e.vector("hello")
    assert (len(v), tokens) == (embeddings.DIMENSIONS, 7)
    r = seen[0]
    assert str(r.url) == "http://gw/v1/embeddings"
    assert r.headers["authorization"] == "Bearer k" and r.headers["x-title"] == "aiops"
    assert json.loads(r.content) == {"model": MODEL, "input": "hello", "dimensions": 512}
    with pytest.raises(ValueError, match="3 dimensions"):
        await e.vector("short")


def test_embeddings_need_the_gateway() -> None:
    with pytest.raises(ValidationError, match="AIOPS_MODEL_BASE_URL"):
        Settings(_env_file=None, embedding_model=MODEL)


def test_who_gets_an_embedder() -> None:
    on = make_contract(integrations=[{"name": "kubernetes"}, {"name": "incidents"}])
    off = make_contract(
        integrations=[{"name": "kubernetes"}, {"name": "incidents", "embeddings": False}]
    )
    without = make_contract()
    store: Any = object()
    assert isinstance(embeddings.for_contract(hub(), store, on), embeddings.Embedder)
    assert embeddings.for_contract(hub(), store, off) is None
    assert embeddings.for_contract(hub(), store, without) is None
    assert embeddings.for_contract(hub(), None, on) is None
    assert embeddings.for_contract(Settings(_env_file=None), store, on) is None


def wait_embedded(database_url: str, id_: str) -> str | None:
    for _ in range(100):
        with psycopg.connect(database_url) as conn:
            row = conn.execute(
                "select embedding_model from investigations where id = %s", (id_,)
            ).fetchone()
        if row and row[0]:
            return str(row[0])
        time.sleep(0.02)
    return None


@pytest.mark.parametrize("on", [True, False])
def test_the_hub_embeds_a_finished_triage_report(
    on: bool, fake_cluster: Any, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fixed(self: Any, text: str) -> tuple[list[float], int]:
        return vec(0), 5

    monkeypatch.setattr(embeddings.Embedder, "vector", fixed)
    # No gateway URL: it would make the scripted model answer by provider strategy.
    settings = Settings(_env_file=None, model="fake", database_url=SecretStr(database_url))
    settings = settings.model_copy(update={"embedding_model": MODEL})
    acme = {"integrations": [{"name": "kubernetes"}, {"name": "incidents", "embeddings": on}]}
    with client(settings, fake_cluster, call("TriageReport", "c1", **REPORT), acme=acme) as c:
        tid = c.post(URL, json=ALERT, headers=HOOK).json()["investigation"]
        wait_status(c, tid, "done")
        found = wait_embedded(database_url, tid) if on else None
    assert found == (MODEL if on else None)


async def test_the_backfill_embeds_what_is_missing_per_contract(
    store: Store, database_url: str, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fixed(self: Any, text: str) -> tuple[list[float], int]:
        return vec(0), 5

    monkeypatch.setattr(embeddings.Embedder, "vector", fixed)
    on = make_contract(integrations=[{"name": "kubernetes"}, {"name": "incidents"}])
    no = [{"name": "kubernetes"}, {"name": "incidents", "embeddings": False}]
    off = make_contract(contract_id="bank", integrations=no)
    monkeypatch.setattr(contracts, "load", lambda _: {"acme": on, "bank": off})
    await store.insert(past("a1", "x"))
    await store.insert(past("a2", "x"))
    await embedded(store, "a2", vec(1))  # already done
    await store.insert(past("b1", "x", contract_id="bank"))
    settings = hub(database_url=SecretStr(database_url), contracts_dir=tmp_path)
    assert await cli.embed_past(settings) == 0
    assert await store.unembedded("acme", MODEL) == []
    assert [r["id"] for r in await store.unembedded("bank", MODEL)] == ["b1"]
    assert [r[0] for r in usage(database_url)] == ["a1"]


async def test_the_backfill_fails_when_an_embedding_failed(
    store: Store, database_url: str, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(self: Any, text: str) -> tuple[list[float], int]:
        raise httpx.ConnectError("gateway down")

    monkeypatch.setattr(embeddings.Embedder, "vector", down)
    on = make_contract(integrations=[{"name": "kubernetes"}, {"name": "incidents"}])
    monkeypatch.setattr(contracts, "load", lambda _: {"acme": on})
    await store.insert(past("a1", "x"))
    settings = hub(database_url=SecretStr(database_url), contracts_dir=tmp_path)
    assert await cli.embed_past(settings) == 1
    assert [r["id"] for r in await store.unembedded("acme", MODEL)] == ["a1"]


def test_a_budget_needs_the_embedding_model_priced() -> None:
    from aiops_agent.api import create_app

    incidents = [{"name": "kubernetes"}, {"name": "incidents"}]
    budget = make_contract(integrations=incidents, monthly_budget_usd=5)
    settings = hub(approver_token=SecretStr("a"), database_url=SecretStr("postgresql://x/y"))
    settings.model_prices = {"fake": PRICE}
    with pytest.raises(RuntimeError, match=r"embedding model .* has no price"):
        create_app(settings, by_id={"acme": budget})
    settings.model_prices = {"fake": PRICE, MODEL: PRICE}
    create_app(settings, by_id={"acme": budget})
    off = [{"name": "kubernetes"}, {"name": "incidents", "embeddings": False}]
    settings.model_prices = {"fake": PRICE}
    create_app(settings, by_id={"acme": make_contract(integrations=off, monthly_budget_usd=5)})
