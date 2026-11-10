-- What started an Investigation, as received: the Alert group, or {"question": ...}
-- for a Question's first message. Turns a finished Investigation into a Scenario.
alter table investigations add column input jsonb;
