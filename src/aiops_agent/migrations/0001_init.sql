-- Hub state. Times are epoch seconds from the Hub's clock, never mixed with now().
create table investigations (
    id text primary key,
    kind text not null,
    contract_id text not null,
    title text not null,
    group_key text not null default '',
    group_resolved boolean not null default false,
    status text not null,
    started double precision not null,
    report jsonb,
    pending jsonb not null default '[]',
    executed_actions jsonb not null default '[]',
    error text,
    deadline double precision
);
create index investigations_group on investigations (contract_id, group_key);
create index investigations_started on investigations (started desc);

-- The dedup memory: per Contract and group key, its latest Investigation and every
-- fingerprint seen since.
create table alert_groups (
    contract_id text not null,
    group_key text not null,
    started double precision not null,
    investigation_id text not null references investigations (id),
    seen text[] not null,
    primary key (contract_id, group_key)
);

-- Every Approval decision and Stale rejection: who decided what, when.
create table decisions (
    id bigserial primary key,
    investigation_id text not null references investigations (id),
    approve boolean not null,
    actions jsonb not null,
    message text not null default '',
    decided_by text not null,
    at double precision not null
);
create index decisions_investigation on decisions (investigation_id);
