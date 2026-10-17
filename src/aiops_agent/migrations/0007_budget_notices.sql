-- Budget notices already posted: one per Contract, month and level (80, 100), so
-- concurrent Runs crossing a line together post it once.
create table budget_notices (
    contract_id text not null,
    month double precision not null,
    level integer not null,
    at double precision not null,
    primary key (contract_id, month, level)
);
