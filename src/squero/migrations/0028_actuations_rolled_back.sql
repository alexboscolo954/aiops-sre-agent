-- Slice 12.4: an Actuation may also be a rollback: the Actuator put a container's pods
-- back to their template's requests because its Sizing made them unhealthy.
alter table actuations drop constraint actuations_outcome_check;
alter table actuations add constraint actuations_outcome_check
    check (outcome in ('applied', 'skipped', 'failed', 'handed_back', 'rolled_back'));
