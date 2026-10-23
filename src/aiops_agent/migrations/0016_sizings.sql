-- Stored Sizings (slice 9.4): a run per Contract each hour, a row per container.
create table sizing_runs (
    id bigserial primary key,
    contract_id text not null,
    at double precision not null,
    clusters jsonb not null default '{}'  -- cluster -> null when read, else why not; {} while running
);
create index on sizing_runs (contract_id, at);
create table sizings (
    run_id bigint not null references sizing_runs on delete cascade,
    contract_id text not null,
    cluster text not null,
    namespace text not null,
    kind text not null,
    name text not null,
    container text not null,
    row jsonb not null,  -- sizing.rows(): policy, state, pods, cpu, memory, waste, risks
    primary key (run_id, cluster, namespace, kind, name, container)
);
create index on sizings (contract_id, cluster, namespace, kind, name, container);
