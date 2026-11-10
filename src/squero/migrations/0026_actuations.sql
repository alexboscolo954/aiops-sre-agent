-- Actuations (slice 12.1): what an Actuator reports it did with one container's Approved
-- Sizing (run_id): applied, skipped or failed, the requests it set (null: left as they
-- were), on how many pods, and why. `at` is the Actuator's own time, so a report it
-- sends again after a failed POST is stored once. Kept 90 days.
create table actuations (
    contract_id text not null,
    cluster text not null,
    namespace text not null,
    kind text not null,
    name text not null,
    container text not null,
    run_id bigint not null,
    outcome text not null check (outcome in ('applied', 'skipped', 'failed')),
    cpu double precision,
    memory double precision,
    pods integer not null,
    reason text not null,
    at double precision not null,
    received_at double precision not null,
    primary key (contract_id, cluster, namespace, kind, name, container, run_id, at)
);
