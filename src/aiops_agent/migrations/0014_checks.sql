-- Scheduled Checks (slice 8.1): a Check's verdict, and one schedule row per Check.
alter table investigations add column check_result jsonb;
create table check_schedules (
    contract_id text not null,
    name text not null,
    schedule text not null,  -- "<cron> <timezone>": a change recomputes next_due
    next_due double precision not null,
    last_id text,  -- the latest Run's Investigation: no new one while it is open
    failing_id text,  -- the Open failure's Investigation, whose thread later Runs reply in
    skipped_at double precision,
    skipped_reason text,
    primary key (contract_id, name)
);
