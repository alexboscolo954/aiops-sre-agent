-- Slice 13.1b: an Actuator may report a Step-up it made (`stepped_up`): a container's
-- memory limit and request raised after an OOM kill at a memory limit (ADR 0005); and
-- its end (`step_ended`), which is no Sizing's hand-back.
alter table actuations drop constraint actuations_outcome_check;
alter table actuations add constraint actuations_outcome_check
    check (outcome in ('applied', 'skipped', 'failed', 'handed_back', 'rolled_back', 'reverted',
                       'oom_killed', 'stepped_up', 'step_ended'));
