-- Slice 12.2: an Actuation may also be a hand-back: a person changed the template's
-- requests of a container the Actuator held (or its Deployment is gone), so it lets go.
alter table actuations drop constraint actuations_outcome_check;
alter table actuations add constraint actuations_outcome_check
    check (outcome in ('applied', 'skipped', 'failed', 'handed_back'));
