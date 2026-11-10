-- Similar incidents: full-text search over a Contract's past Reports. Only the
-- Report's string values and the title are indexed, never its JSON keys.
alter table investigations add column report_search tsvector generated always as (
    to_tsvector('english', title)
    || jsonb_to_tsvector('english', coalesce(report, '{}'::jsonb), '["string"]')
) stored;
create index investigations_report_search on investigations using gin (report_search);
