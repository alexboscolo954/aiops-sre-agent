-- Every model call's tokens, and its cost at the price when it ran (null when the
-- model has no price). Spend per Contract per month is a sum over these.
create table usage (
    id bigserial primary key,
    investigation_id text not null references investigations (id),
    contract_id text not null,
    model text not null,
    input_tokens integer not null,
    output_tokens integer not null,
    cost_usd double precision,
    at double precision not null
);
create index usage_contract_at on usage (contract_id, at);
create index usage_investigation on usage (investigation_id);
