-- Cloud list prices (slice 10.4): what each cluster's nodes are (read from its
-- Prometheus every hourly run, the latest kept) and the on-demand price per hour of
-- each (provider, region, instance type) the Hub has looked up, kept with its age.
create table cluster_nodes (
    contract_id text not null,
    cluster text not null,
    at double precision not null,
    facts jsonb not null,  -- {"nodes": [{provider, region, type, vcpu, gib}], "problem": text|null}
    primary key (contract_id, cluster)
);

create table list_prices (
    provider text not null,
    region text not null,
    instance_type text not null,
    usd_hour double precision,  -- the last good price, null before the first
    ok_at double precision,  -- when it was read
    tried_at double precision not null,
    error text,  -- why the last try failed, null when it worked
    primary key (provider, region, instance_type)
);
