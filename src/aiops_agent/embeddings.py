"""Similar incidents by meaning (slice 7.4): Report embeddings in pgvector, next to the
full-text search of 7.1.

The Hub's model gateway (AIOPS_MODEL_BASE_URL, AIOPS_MODEL_API_KEY) embeds with
AIOPS_EMBEDDING_MODEL, e.g. openai/text-embedding-3-small on OpenRouter. Off when that is
unset, and for a Contract whose incidents integration says `embeddings: false`: its
Report text then never goes to the embedding model. A failed embedding never fails a
Triage or a search: the Report is still found by its words.
"""

import logging
from typing import Any

import httpx

from aiops_agent import masking
from aiops_agent.config import Settings
from aiops_agent.contracts import Contract, Incidents
from aiops_agent.models import TriageReport
from aiops_agent.store import Store

DIMENSIONS = 512  # the column's size (migration 0013)
MAX_CHARS = 8000  # well under the model's 8k-token input
log = logging.getLogger("aiops.embeddings")


def report_text(title: str, report: dict[str, Any]) -> str:
    """What a Report is about: what full-text search indexes, without the plan."""
    r = TriageReport.model_validate(report)
    parts = [title, r.summary, r.category, r.probable_root_cause, *r.affected]
    parts += [e.finding for e in r.evidence]
    return "\n".join(parts)[:MAX_CHARS]


class Embedder:
    """One Contract's embeddings; its usage is recorded under that Contract."""

    def __init__(
        self,
        settings: Settings,
        store: Store,
        contract_id: str,
        transport: httpx.AsyncBaseTransport | None = None,
        masker: masking.Masker | None = None,
    ) -> None:
        assert settings.embedding_model  # Settings: and a gateway
        self.settings, self.store, self.contract_id = settings, store, contract_id
        self.model = settings.embedding_model
        self.max_distance = settings.embedding_max_distance
        self.transport, self.masker = transport, masker

    async def vector(self, text: str) -> tuple[list[float], int]:
        """The embedding and its input tokens. The text goes out as the model sees it:
        redacted, and masked by the Contract's Data policy (slice 6.4)."""
        text = masking.outgoing(self.masker, text)
        s = self.settings
        key = s.model_api_key.get_secret_value() if s.model_api_key else ""
        async with httpx.AsyncClient(transport=self.transport, timeout=15) as http:
            r = await http.post(
                f"{(s.model_base_url or '').rstrip('/')}/embeddings",
                headers={"Authorization": f"Bearer {key}", **s.model_headers},
                json={"model": self.model, "input": text, "dimensions": DIMENSIONS},
            )
            r.raise_for_status()
            body = r.json()
        found = [float(x) for x in body["data"][0]["embedding"]]
        if len(found) != DIMENSIONS:
            raise ValueError(f"{len(found)} dimensions, not {DIMENSIONS}")
        return found, int(body.get("usage", {}).get("prompt_tokens", 0))

    async def _used(self, investigation_id: str | None, tokens: int) -> None:
        price = self.settings.model_prices.get(self.model)
        cost = price.cost(tokens, 0) if price else None
        await self.store.record_usage(
            investigation_id, self.contract_id, self.model, tokens, 0, cost
        )

    async def query(self, text: str) -> list[float] | None:
        """A search's embedding; None when it failed (the search then uses words only)."""
        try:
            found, tokens = await self.vector(text)
        except Exception as e:  # never fail the search
            log.warning("contract %s: search embedding failed: %s", self.contract_id, e)
            return None
        await self._used(None, tokens)
        return found

    async def index(self, row: dict[str, Any]) -> bool:
        """Embed one of this Contract's finished Reports (id, title, report) and store
        it. False when it failed: the Report stays findable by its words."""
        try:
            found, tokens = await self.vector(report_text(row["title"], row["report"]))
        except Exception as e:  # never fail the Triage
            log.warning("investigation %s: embedding failed: %s", row["id"], e)
            return False
        await self._used(row["id"], tokens)
        return await self.store.set_embedding(self.contract_id, row["id"], self.model, found)


def on(settings: Settings, contract: Contract) -> bool:
    """The Hub has an embedding model and the Contract lists incidents with embeddings on."""
    lists = any(isinstance(i, Incidents) and i.embeddings for i in contract.integrations)
    return bool(settings.embedding_model) and lists


def for_contract(settings: Settings, store: Store | None, contract: Contract) -> Embedder | None:
    """The Contract's Embedder, when on() and there is a database."""
    if store is None or not on(settings, contract):
        return None
    return Embedder(settings, store, contract.id, masker=masking.for_contract(contract))
