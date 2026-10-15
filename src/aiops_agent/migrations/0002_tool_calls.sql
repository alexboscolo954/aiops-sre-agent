-- Every tool call of an Investigation: the audit log, and the raw results (before
-- the cap, after redaction) that turn an Investigation into a Scenario (slice 2.6).
create table tool_calls (
    id bigserial primary key,
    investigation_id text not null references investigations (id),
    contract_id text not null,
    tool text not null,
    args jsonb not null,
    result text not null,
    is_error boolean not null,
    at double precision not null
);
create index tool_calls_investigation on tool_calls (investigation_id, id);
