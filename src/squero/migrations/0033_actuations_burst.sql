-- Slice 13.3b: an Actuator may report a Burst it made (`burst`): a throttled container's
-- CPU limit raised (ADR 0005); its end (`burst_ended`); and a container the Hub's read
-- says is throttled of which it made none (`throttled`), with why.
alter table actuations drop constraint actuations_outcome_check;
alter table actuations add constraint actuations_outcome_check
    check (outcome in ('applied', 'skipped', 'failed', 'handed_back', 'rolled_back', 'reverted',
                       'oom_killed', 'stepped_up', 'step_ended',
                       'throttled', 'burst', 'burst_ended'));
