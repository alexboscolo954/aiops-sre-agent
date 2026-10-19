The latest rollout (revision 2, about 48 seconds before the check) removed the `DATABASE_URL` environment variable from the `app` container. The image did not change and stayed `python:3.12-alpine`. Revision 1 had `DATABASE_URL` set, and revision 2 has no env vars. Since the rollout, the deployment has 0 of 1 replicas ready and `Available` is False (`MinimumReplicasUnavailable`). I did not check the pod logs, so I can't confirm the missing variable is what keeps the pod from becoming ready. It is the only change in the rollout, so it is the likely cause. To restore the previous config, re-add `DATABASE_URL` to the checkout deployment (for example with `kubectl set env` or by rolling back to revision 1), after confirming the right value.

**Evidence**
- `kubernetes_recent_changes`: checkout revision 2 at 48s: change "rollout", diff {"env_removed": {"app": ["DATABASE_URL"]}}; revision 1 created 2m ago with no diff.
- `kubernetes_describe_deployment`: checkout rollout_history: revision 2 (replicaset checkout-869fc5bcc6, 36s old) config app env [] with image python:3.12-alpine; revision 1 (checkout-67d9799c78, 2m old) config app env ["DATABASE_URL"] with image python:3.12-alpine.
- `kubernetes_describe_deployment`: checkout replicas desired 1, ready 0; conditions Available=False reason MinimumReplicasUnavailable, Progressing=True reason NewReplicaSetAvailable.

**Tool calls**
1. `kubernetes_describe_deployment`
2. `kubernetes_recent_changes`
3. `kubernetes_describe_deployment`
4. `runbooks_read_runbook`
