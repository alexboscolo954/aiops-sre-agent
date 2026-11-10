-- Similar incidents by meaning (slice 7.4): a Report's embedding, next to the model
-- that made it. Another model's vectors are never compared; re-embed after a change.
create extension if not exists vector;
alter table investigations add column embedding vector(512), add column embedding_model text;
-- A search's embedding belongs to no Investigation, only to its Contract.
alter table usage alter column investigation_id drop not null;
