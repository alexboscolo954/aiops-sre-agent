-- Related alert groups: an Alert group that joined an open Triage instead of
-- starting one. As received, with the match labels it shared; investigated only if
-- the Operator has it triaged separately (separate_id, that Triage).
create table related_groups (
    id bigserial primary key,
    investigation_id text not null references investigations (id),
    contract_id text not null,
    group_key text not null,
    title text not null,
    input jsonb not null,
    matched jsonb not null,
    louder boolean not null,
    at double precision not null,
    separate_id text references investigations (id)
);
create index related_groups_investigation on related_groups (investigation_id, id);
