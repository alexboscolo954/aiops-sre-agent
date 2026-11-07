-- Approved Sizings (slice 11.2b): one container's Sizing the Operator approved, with the
-- exact requests approved (null: leave that one as it is). Current until a later run reads
-- its cluster. No foreign key to sizing_runs: pruning a run keeps the record.
create table approved_sizings (
    contract_id text not null,
    run_id bigint not null,
    cluster text not null,
    namespace text not null,
    kind text not null,
    name text not null,
    container text not null,
    cpu double precision,
    memory double precision,
    approved_by text not null,
    approved_at double precision not null,
    primary key (contract_id, run_id, cluster, namespace, kind, name, container)
);
