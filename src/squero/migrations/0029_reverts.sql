-- Slice 12.6a: Reverts, the Operator's undo of what the Actuator holds for a container.
-- One is pending until the Actuator reports a `reverted` Actuation of that container
-- received after it; the newest one also stops Automation of the container until a
-- later approval. Kept as long as the Contract: a row per Revert asked.
create table reverts (
    id bigserial primary key,
    contract_id text not null,
    cluster text not null,
    namespace text not null,
    kind text not null,
    name text not null,
    container text not null,
    asked_by text not null,
    asked_at double precision not null
);
create index on reverts (contract_id, cluster);
alter table actuations drop constraint actuations_outcome_check;
alter table actuations add constraint actuations_outcome_check
    check (outcome in ('applied', 'skipped', 'failed', 'handed_back', 'rolled_back', 'reverted'));
