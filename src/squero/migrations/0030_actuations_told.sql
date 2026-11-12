-- Slice 12.9c: whether the Operator was told of a Rollback. The Hub posts it to Slack
-- after storing it, and again later if Slack didn't take it, so an alert is late, never
-- lost. Rows stored before this slice were told (or never will be): true. Last column:
-- the insert names none.
alter table actuations add column told boolean not null default true;
-- The untold are few and read each scheduler tick: found without reading the rest.
create index actuations_untold on actuations (contract_id, cluster, received_at) where not told;
