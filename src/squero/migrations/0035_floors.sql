-- Floors (slice 14.1b): the minimum replicas the Hub computes for each Workload with an
-- autoscaler, from its stored Needs and the HPA's minimum and maximum as each hourly run
-- reads them; a cluster's latest, replaced on every run that read it.
create table floors (
    contract_id text not null,
    cluster text not null,
    at double precision not null,  -- the run that computed them
    floors jsonb not null,  -- a list, one per Workload with an HPA (sizing.floors())
    primary key (contract_id, cluster)
);
