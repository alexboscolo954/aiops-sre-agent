-- Needs (slice 14.1a): the replicas each Workload with an autoscaler needed, as every
-- UTC hour's peak, read from kube-state-metrics' HPA series on each hourly run and
-- kept 8 weeks: a Weekly profile needs more weeks than most Prometheus keep.
create table needs (
    contract_id text not null,
    cluster text not null,
    namespace text not null,
    kind text not null,
    name text not null,
    hour double precision not null,  -- the UTC hour's start
    need double precision not null,  -- its peak, in replicas, not rounded
    primary key (contract_id, cluster, namespace, kind, name, hour)
);
