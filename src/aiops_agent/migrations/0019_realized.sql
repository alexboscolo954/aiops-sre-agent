-- Realized Savings (slice 10.3b): a container's request lowered to a Sizing, per
-- resource, as an hourly run saw it; priced when shown. A later rise raises `after`
-- back toward `before`, and at `before` the row is deleted.
create table realized (
    id bigserial primary key,
    contract_id text not null,
    cluster text not null,
    namespace text not null,
    kind text not null,
    name text not null,
    container text not null,
    resource text not null check (resource in ('cpu', 'memory')),
    at double precision not null,  -- the run that saw the drop
    prev_run bigint not null,  -- the run it was compared with: one row per drop
    before double precision not null,  -- the request per pod before
    after double precision not null,  -- and after; raised by a later rise
    sizing double precision not null,  -- the Sizing it matched
    unique (contract_id, cluster, namespace, kind, name, container, resource, prev_run)
);
create index on realized (contract_id);
