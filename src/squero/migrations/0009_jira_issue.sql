-- The Contract's Jira issue for a Report, filed once by the Operator: which key,
-- who, and when it was claimed (claimed without a key: being filed, or unknown).
alter table investigations add column jira_issue text,
    add column jira_by text,
    add column jira_at double precision;
