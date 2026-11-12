-- Slice 13.1a: an Actuator may report an OOM kill it saw of an automated container
-- (`oom_killed`), which changes nothing.
alter table actuations drop constraint actuations_outcome_check;
alter table actuations add constraint actuations_outcome_check
    check (outcome in ('applied', 'skipped', 'failed', 'handed_back', 'rolled_back', 'reverted',
                       'oom_killed'));
