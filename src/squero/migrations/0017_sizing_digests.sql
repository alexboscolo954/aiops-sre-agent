-- Weekly Sizing digest (slice 9.5b): one schedule row per Contract that gets one.
create table sizing_digests (
    contract_id text primary key,
    schedule text not null,  -- "<cron> <timezone>": a change recomputes next_due
    next_due double precision not null,
    last_at double precision  -- the latest due time claimed (and posted)
);
