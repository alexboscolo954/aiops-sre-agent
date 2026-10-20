-- Deploy verification (slice 8.2): one row per verification, pending until it fires.
-- Deploys in one namespace join its pending row; it survives a restart.
create table deploy_checks (
    id bigserial primary key,
    contract_id text not null,
    cluster text not null,
    namespace text not null,
    state text not null default 'pending',  -- pending, started, skipped
    first_seen double precision not null,
    due double precision not null,
    changes jsonb not null,  -- identities only: {namespace, object, revision}
    -- Workloads not running ready at the poll before the first deploy (null: unknown).
    failing_before jsonb,
    investigation_id text,
    skipped_reason text
);
create unique index deploy_checks_pending on deploy_checks (contract_id, cluster, namespace)
    where state = 'pending';
create index deploy_checks_contract on deploy_checks (contract_id, id desc);
