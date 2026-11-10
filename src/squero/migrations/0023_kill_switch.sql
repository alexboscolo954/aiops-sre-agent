-- The Kill switch (slice 11.2a): a row while a Contract's is on. Who turned it on and
-- when; turning it off deletes the row (the Hub's log says who).
create table kill_switches (
    contract_id text primary key,
    set_by text not null,
    set_at double precision not null
);
