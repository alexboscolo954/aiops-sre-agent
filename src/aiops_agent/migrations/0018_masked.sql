-- Masking (slice 6.4): the placeholders an Investigation's model calls sent, never
-- the values they stand for. The console counts them per kind.
create table masked (
    investigation_id text not null references investigations (id),
    contract_id text not null,
    placeholder text not null,  -- <host-3f9a1c2e>
    primary key (investigation_id, placeholder)
);
