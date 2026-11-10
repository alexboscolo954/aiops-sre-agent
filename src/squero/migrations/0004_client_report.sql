-- A Client report goes out once: when, and which Operator sent it.
alter table investigations add column client_sent_at double precision,
    add column client_sent_by text;
