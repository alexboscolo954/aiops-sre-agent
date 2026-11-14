-- Realized Floor savings (slice 14.1c): an HPA's minimum lowered while the Hub showed a
-- Floor below it, as an hourly run saw it; worth what it no longer holds, priced when
-- shown. A later rise raises `after` back toward `before`, and at `before` the row is
-- deleted.
create table floor_drops (
    id bigserial primary key,
    contract_id text not null,
    cluster text not null,
    namespace text not null,
    kind text not null,
    name text not null,
    at double precision not null,  -- the run that saw the minimum lowered
    before double precision not null,  -- the HPA's minimum before
    after double precision not null,  -- what it counts down to: never below `floor`; raised by a rise
    floor double precision not null,  -- the Floor shown then
    unique (contract_id, cluster, namespace, kind, name, at)
);
create index on floor_drops (contract_id);
