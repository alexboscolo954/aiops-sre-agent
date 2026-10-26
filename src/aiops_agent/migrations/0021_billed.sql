-- AWS bills (slice 10.5a): what Cost Explorer says a cluster's tagged EC2 compute cost
-- each UTC day (usage before credits), and when the Hub last tried to read it.
create table billed_costs (
    contract_id text not null,
    cluster text not null,
    day text not null,  -- YYYY-MM-DD, UTC
    amount double precision not null,
    currency text not null,
    estimated boolean not null,  -- AWS still says the day may change
    primary key (contract_id, cluster, day)
);

create table billing_tries (
    contract_id text not null,
    cluster text not null,
    tried_at double precision not null,
    ok_at double precision,  -- the last good read, kept through a failure
    error text,  -- why the last try failed, null when it worked
    primary key (contract_id, cluster)
);
