"""Postgres state for the Hub: Investigations, the dedup memory, Approval decisions.

One pool serves this store and the LangGraph checkpointer, with the connection
settings the checkpointer needs (autocommit, no prepared statements, dict rows).
Migrations are numbered .sql files in migrations/, applied once each at startup.
"""

import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection, Rollback
from psycopg.errors import UniqueViolation
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from aiops_agent.models import AlertGroup, Investigation

Pool = AsyncConnectionPool[AsyncConnection[DictRow]]
MIGRATIONS = Path(__file__).parent / "migrations"
MIGRATION_LOCK = 4_242_001  # pg_advisory_xact_lock key: one Hub migrates at a time
COLUMNS = (
    "id, kind, contract_id, title, group_key, group_resolved, status, started, report, "
    "pending, executed_actions, error, deadline, slack_channel, slack_ts, client_sent_at, "
    "client_sent_by, answer, last_mention_ts, input, jira_issue, jira_by, jira_at"
)


def now() -> float:
    """The one clock for stored times and comparisons."""
    return time.time()


@asynccontextmanager
async def connect(url: str) -> AsyncIterator[Pool]:
    pool: Pool = AsyncConnectionPool(
        url,
        connection_class=AsyncConnection[DictRow],
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    )
    await pool.open()
    try:
        yield pool
    finally:
        await pool.close()


def month_start(at: float) -> float:
    """The start of `at`'s calendar month, UTC: budgets are monthly."""
    day = datetime.fromtimestamp(at, UTC)
    return day.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()


def _investigation(row: dict[str, Any]) -> Investigation:
    return Investigation.model_validate(row)


INSERT = (
    f"insert into investigations ({COLUMNS}) values "  # noqa: S608 - fixed columns
    f"({', '.join(['%s'] * len(COLUMNS.split(',')))})"
)


def _row(t: Investigation) -> tuple[Any, ...]:
    """The values for INSERT, in COLUMNS order."""
    return (
        t.id,
        t.kind,
        t.contract_id,
        t.title,
        t.group_key,
        t.group_resolved,
        t.status,
        t.started,
        Jsonb(t.report.model_dump(mode="json")) if t.report else None,
        Jsonb(t.pending),
        Jsonb(t.executed_actions),
        t.error,
        t.deadline,
        t.slack_channel,
        t.slack_ts,
        t.client_sent_at,
        t.client_sent_by,
        Jsonb(t.answer.model_dump(mode="json")) if t.answer else None,
        t.last_mention_ts,
        Jsonb(t.input) if t.input is not None else None,
        t.jira_issue,
        t.jira_by,
        t.jira_at,
    )


class Store:
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def migrate(self) -> None:
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute("select pg_advisory_xact_lock(%s)", (MIGRATION_LOCK,))
            await conn.execute(
                "create table if not exists schema_migrations "
                "(version text primary key, applied double precision not null)"
            )
            rows = await (await conn.execute("select version from schema_migrations")).fetchall()
            done = {r["version"] for r in rows}
            for path in sorted(MIGRATIONS.glob("*.sql")):
                if path.stem in done:
                    continue
                # Unprepared: a migration file holds several statements.
                await conn.execute(path.read_text().encode(), prepare=False)
                await conn.execute(
                    "insert into schema_migrations values (%s, %s)", (path.stem, now())
                )

    async def _one(self, sql: str, args: tuple[Any, ...]) -> dict[str, Any] | None:
        async with self.pool.connection() as conn:
            row: dict[str, Any] | None = await (await conn.execute(sql, args)).fetchone()
            return row

    async def _exec(self, sql: str, args: tuple[Any, ...]) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(sql, args)

    async def _all(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        async with self.pool.connection() as conn:
            rows: list[dict[str, Any]] = await (await conn.execute(sql, args)).fetchall()
            return rows

    async def insert(self, t: Investigation) -> None:
        await self._exec(INSERT, _row(t))

    async def set_slack_thread(self, investigation_id: str, channel: str, ts: str) -> bool:
        """Only while it has none: a thread, once started, is never replaced."""
        row = await self._one(
            "update investigations set slack_channel = %s, slack_ts = %s "
            "where id = %s and slack_ts is null returning id",
            (channel, ts, investigation_id),
        )
        return row is not None

    async def claim_client_report(self, investigation_id: str, by: str) -> float | None:
        """Take the one send of a finished Report: its time, or None when it was
        already sent (or isn't finished)."""
        at = now()
        row = await self._one(
            "update investigations set client_sent_at = %s, client_sent_by = %s "
            "where id = %s and status = 'done' and report is not null "
            "and client_sent_at is null returning id",
            (at, by, investigation_id),
        )
        return at if row else None

    async def release_client_report(self, investigation_id: str, at: float) -> None:
        """The post failed: free the send for a retry, unless it was claimed again."""
        await self._exec(
            "update investigations set client_sent_at = null, client_sent_by = null "
            "where id = %s and client_sent_at = %s",
            (investigation_id, at),
        )

    async def claim_jira(self, investigation_id: str, by: str) -> float | None:
        """Take the one Jira issue of a finished Report: its time, or None when it
        was already claimed (filed, being filed, or unknown) or isn't finished."""
        at = now()
        row = await self._one(
            "update investigations set jira_at = %s, jira_by = %s "
            "where id = %s and status = 'done' and report is not null "
            "and jira_at is null returning id",
            (at, by, investigation_id),
        )
        return at if row else None

    async def set_jira_issue(self, investigation_id: str, at: float, key: str) -> None:
        await self._exec(
            "update investigations set jira_issue = %s where id = %s and jira_at = %s",
            (key, investigation_id, at),
        )

    async def release_jira(self, investigation_id: str, at: float) -> None:
        """Jira refused it: free the claim for a retry, unless it was claimed again."""
        await self._exec(
            "update investigations set jira_at = null, jira_by = null "
            "where id = %s and jira_at = %s and jira_issue is null",
            (investigation_id, at),
        )

    async def insert_question(self, t: Investigation) -> bool:
        """False when its thread already has an Investigation (Slack redelivered
        the mention, or the thread is taken)."""
        try:
            await self.insert(t)
        except UniqueViolation:
            return False
        return True

    async def by_thread(self, channel: str, ts: str) -> Investigation | None:
        row = await self._one(
            f"select {COLUMNS} from investigations "  # noqa: S608 - fixed columns
            "where slack_channel = %s and slack_ts = %s",
            (channel, ts),
        )
        return _investigation(row) if row else None

    async def claim_follow_up(self, investigation_id: str, mention_ts: str) -> bool:
        """One Run at a time per Question, and each mention at most once: only a
        finished Question, and only with a mention newer than the last one."""
        row = await self._one(
            "update investigations set status = 'running', error = null, last_mention_ts = %s "
            "where id = %s and kind = 'question' and status in ('done', 'failed') "
            "and (last_mention_ts is null or last_mention_ts < %s) returning id",
            (mention_ts, investigation_id, mention_ts),
        )
        return row is not None

    async def save(self, t: Investigation) -> None:
        """Everything a Run changes. Never group_resolved (only the resolve path sets
        it, so a Run that finishes after a resolve can't clear it), nor the Slack
        thread (set_slack_thread), nor the Client report's send, nor the last
        mention (claim_follow_up)."""
        await self._exec(
            "update investigations set status = %s, report = %s, pending = %s, "
            "executed_actions = %s, error = %s, deadline = %s, answer = %s where id = %s",
            (
                t.status,
                Jsonb(t.report.model_dump(mode="json")) if t.report else None,
                Jsonb(t.pending),
                Jsonb(t.executed_actions),
                t.error,
                t.deadline,
                Jsonb(t.answer.model_dump(mode="json")) if t.answer else None,
                t.id,
            ),
        )

    async def get(self, investigation_id: str) -> Investigation | None:
        row = await self._one(
            f"select {COLUMNS} from investigations where id = %s",  # noqa: S608
            (investigation_id,),
        )
        return _investigation(row) if row else None

    async def recent(self, limit: int = 50, contract_id: str | None = None) -> list[Investigation]:
        """Newest first; one Contract's only when contract_id is given."""
        rows = await self._all(
            f"select {COLUMNS} from investigations "  # noqa: S608 - fixed columns
            "where %s::text is null or contract_id = %s order by started desc limit %s",
            (contract_id, contract_id, limit),
        )
        return [_investigation(r) for r in rows]

    async def last_done(self) -> dict[str, Investigation]:
        """Each Contract's latest Investigation that finished with a Report or Answer."""
        rows = await self._all(
            f"select distinct on (contract_id) {COLUMNS} from investigations "  # noqa: S608
            "where status = 'done' order by contract_id, started desc"
        )
        return {r["contract_id"]: _investigation(r) for r in rows}

    async def tool_calls(self, investigation_id: str) -> list[dict[str, Any]]:
        return await self._all(
            "select tool, args, result, is_error, at from tool_calls "
            "where investigation_id = %s order by id",
            (investigation_id,),
        )

    async def decisions(self, investigation_id: str) -> list[dict[str, Any]]:
        return await self._all(
            "select approve, actions, message, decided_by, at from decisions "
            "where investigation_id = %s order by id",
            (investigation_id,),
        )

    async def unfinished(self) -> list[Investigation]:
        rows = await self._all(
            f"select {COLUMNS} from investigations "  # noqa: S608
            "where status in ('running', 'awaiting_approval') order by started"
        )
        return [_investigation(r) for r in rows]

    async def pending_count(self) -> int:
        row = await self._one(
            "select coalesce(sum(jsonb_array_length(pending)), 0) as n from investigations "
            "where status = 'awaiting_approval'",
            (),
        )
        return int(row["n"]) if row else 0

    async def mark_group_resolved(self, contract_id: str, group_key: str) -> list[Investigation]:
        rows = await self._all(
            "update investigations set group_resolved = true "  # noqa: S608 - fixed columns
            f"where contract_id = %s and group_key = %s returning {COLUMNS}",
            (contract_id, group_key),
        )
        return [_investigation(r) for r in rows]

    async def claim(
        self, investigation_id: str, deadline: float | None
    ) -> list[dict[str, Any]] | None:
        """Take a pause's Proposed actions for one decision. Atomic: of an approval, a
        rejection, a timeout and a resolve racing for the same pause, exactly one
        gets the actions; the others get None."""
        row = await self._one(
            "update investigations set status = 'running', pending = '[]', deadline = null "
            "where id = %s and status = 'awaiting_approval' and deadline = %s "
            "returning (select pending from investigations where id = %s) as pending",
            (investigation_id, deadline, investigation_id),
        )
        return row["pending"] if row else None

    async def record_decision(
        self,
        investigation_id: str,
        approve: bool,
        actions: list[dict[str, Any]],
        message: str,
        decided_by: str,
    ) -> None:
        await self._exec(
            "insert into decisions (investigation_id, approve, actions, message, decided_by, at) "
            "values (%s, %s, %s, %s, %s, %s)",
            (investigation_id, approve, Jsonb(actions), message, decided_by, now()),
        )

    async def last_decision(self, investigation_id: str) -> dict[str, Any] | None:
        return await self._one(
            "select approve, actions, message, decided_by, at from decisions "
            "where investigation_id = %s order by id desc limit 1",
            (investigation_id,),
        )

    async def record_tool_call(
        self,
        investigation_id: str,
        contract_id: str,
        tool: str,
        args: dict[str, Any],
        result: str,
        is_error: bool,
    ) -> None:
        await self._exec(
            "insert into tool_calls (investigation_id, contract_id, tool, args, result, "
            "is_error, at) values (%s, %s, %s, %s, %s, %s, %s)",
            (investigation_id, contract_id, tool, Jsonb(args), result, is_error, now()),
        )

    async def record_usage(
        self,
        investigation_id: str,
        contract_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float | None,
    ) -> None:
        await self._exec(
            "insert into usage (investigation_id, contract_id, model, input_tokens, "
            "output_tokens, cost_usd, at) values (%s, %s, %s, %s, %s, %s, %s)",
            (investigation_id, contract_id, model, input_tokens, output_tokens, cost_usd, now()),
        )

    async def month_spend(self, contract_id: str, at: float) -> float:
        """One Contract's cost so far in `at`'s month."""
        row = await self._one(
            "select coalesce(sum(cost_usd), 0) as spent from usage "
            "where contract_id = %s and at >= %s",
            (contract_id, month_start(at)),
        )
        return float(row["spent"]) if row else 0.0

    async def notice_once(self, contract_id: str, at: float, level: int) -> bool:
        """True only for the first caller this month at this level."""
        row = await self._one(
            "insert into budget_notices values (%s, %s, %s, %s) "
            "on conflict do nothing returning level",
            (contract_id, month_start(at), level, at),
        )
        return row is not None

    async def investigation_usage(self, investigation_id: str) -> dict[str, Any]:
        """Tokens, and cost (None when no call was priced)."""
        row = await self._one(
            "select coalesce(sum(input_tokens), 0) as input_tokens, "
            "coalesce(sum(output_tokens), 0) as output_tokens, sum(cost_usd) as cost_usd "
            "from usage where investigation_id = %s",
            (investigation_id,),
        )
        return row or {"input_tokens": 0, "output_tokens": 0, "cost_usd": None}

    async def similar(
        self, contract_id: str, keywords: str, since: float, limit: int
    ) -> list[dict[str, Any]]:
        """This Contract's finished Triage Reports since `since` matching any of the
        words, best match first. Only words reach the query: it never fails to parse."""
        words = re.findall(r"\w+", keywords)[:20]
        if not words:
            return []
        return await self._all(
            "select id, started, title, report from investigations, "
            "websearch_to_tsquery('english', %s) q where contract_id = %s "
            "and kind = 'triage' and status = 'done' and report is not null "
            "and started >= %s and report_search @@ q "
            "order by ts_rank(report_search, q) desc, started desc limit %s",
            (" or ".join(words), contract_id, since, limit),
        )

    async def past_report(self, contract_id: str, investigation_id: str) -> dict[str, Any] | None:
        """One finished Triage Report, only if it is this Contract's."""
        return await self._one(
            "select id, started, title, report, executed_actions, jira_issue "
            "from investigations where id = %s and contract_id = %s "
            "and kind = 'triage' and status = 'done' and report is not null",
            (investigation_id, contract_id),
        )

    async def open_triages(
        self, contract_id: str, since: float, group_key: str
    ) -> list[Investigation]:
        """The Triages a new Alert group of this Contract may join: started since
        `since`, own group still firing, not failed (a refusal fails too). Never one
        whose group the Operator split from this one, either way round, while the
        split-off Triage is within the window too: next incident, they may join."""
        rows = await self._all(
            f"select {COLUMNS} from investigations "  # noqa: S608 - fixed columns
            "where contract_id = %s and kind = 'triage' and started >= %s "
            "and not group_resolved and status <> 'failed' and not exists ("
            " select 1 from related_groups r join investigations i on i.id = r.investigation_id"
            " join investigations s on s.id = r.separate_id"
            " where r.contract_id = %s and s.started >= %s and ("
            "  (r.group_key = %s and i.group_key = investigations.group_key)"
            "  or (i.group_key = %s and r.group_key = investigations.group_key))"
            ") order by started desc",
            (contract_id, since, contract_id, since, group_key, group_key),
        )
        return [_investigation(r) for r in rows]

    async def add_related(
        self,
        investigation_id: str,
        contract_id: str,
        group: AlertGroup,
        matched: dict[str, str],
        louder: bool,
        at: float,
    ) -> int:
        row = await self._one(
            "insert into related_groups (investigation_id, contract_id, group_key, title, "
            "input, matched, louder, at) values (%s, %s, %s, %s, %s, %s, %s, %s) returning id",
            (
                investigation_id,
                contract_id,
                group.groupKey,
                group.title,
                Jsonb(group.model_dump(mode="json")),
                Jsonb(matched),
                louder,
                at,
            ),
        )
        assert row is not None
        return int(row["id"])

    async def related_group(self, related_id: int, investigation_id: str) -> dict[str, Any] | None:
        """One Related alert group, only if it joined that Triage."""
        return await self._one(
            "select group_key, title, input, matched, louder, separate_id from related_groups "
            "where id = %s and investigation_id = %s",
            (related_id, investigation_id),
        )

    async def separate(self, related_id: int, investigation_id: str, t: Investigation) -> bool:
        """Triage a Related alert group separately, once: t, its own Triage, is
        inserted together with the claim, or not at all (a second click)."""
        async with self.pool.connection() as conn, conn.transaction() as tx:
            await conn.execute(INSERT, _row(t))  # first: separate_id references it
            claimed = await (
                await conn.execute(
                    "update related_groups set separate_id = %s where id = %s "
                    "and investigation_id = %s and separate_id is null returning id",
                    (t.id, related_id, investigation_id),
                )
            ).fetchone()
            if claimed is None:
                raise Rollback(tx)
        return claimed is not None

    async def related(self, investigation_id: str) -> list[dict[str, Any]]:
        return await self._all(
            "select id, group_key, title, input, matched, louder, at, separate_id "
            "from related_groups where investigation_id = %s order by id",
            (investigation_id,),
        )

    async def alert_group(
        self, contract_id: str, group_key: str
    ) -> tuple[float, str, set[str]] | None:
        row = await self._one(
            "select started, investigation_id, seen from alert_groups "
            "where contract_id = %s and group_key = %s",
            (contract_id, group_key),
        )
        return (row["started"], row["investigation_id"], set(row["seen"])) if row else None

    async def remember_group(
        self,
        contract_id: str,
        group_key: str,
        started: float,
        investigation_id: str,
        seen: set[str],
    ) -> None:
        await self._exec(
            "insert into alert_groups values (%s, %s, %s, %s, %s) "
            "on conflict (contract_id, group_key) do update set started = excluded.started, "
            "investigation_id = excluded.investigation_id, seen = excluded.seen",
            (contract_id, group_key, started, investigation_id, sorted(seen)),
        )
