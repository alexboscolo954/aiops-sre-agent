-- Feedback: the Operator's verdict on a finished Triage Report, with the correction
-- when it was wrong.
create table feedback (
    id bigserial primary key,
    investigation_id text not null references investigations (id),
    contract_id text not null,
    correct boolean not null,
    correction text,
    by text not null,
    at double precision not null
);
create index feedback_investigation on feedback (investigation_id, id);

-- Teachings: lessons for one Contract's future Investigations. Only approved ones
-- are ever used. A proposed one's text never changes: an edit is part of approving.
create table teachings (
    id bigserial primary key,
    contract_id text not null,
    text text not null,
    alerts jsonb not null default '[]',
    status text not null check (status in ('proposed', 'approved', 'rejected', 'retired')),
    source_id text references investigations (id),  -- null: written by hand
    correction text,  -- the Operator's words it was drafted from
    contradicts bigint references teachings (id),
    proposed_at double precision not null,
    decided_by text,
    decided_at double precision,
    slack_ts text  -- its review post, in the source Investigation's thread
);
create index teachings_contract on teachings (contract_id, status, id);
