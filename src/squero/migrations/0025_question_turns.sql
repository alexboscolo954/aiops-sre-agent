-- Question turns (slice 11.7a): each follow-up on a Question with the Answer it replaced,
-- so the console shows the whole exchange. The first question is the Investigation's title.
create table question_turns (
    id bigserial primary key,
    investigation_id text not null references investigations (id),
    contract_id text not null,
    question text not null,
    answer jsonb,  -- the Answer before this follow-up (null: the Run before had failed)
    at double precision not null
);
create index question_turns_investigation on question_turns (investigation_id, id);
