The latest rollout, revision 2 (ReplicaSet checkout-869fc5bcc6, about 48s before the check), removed the `DATABASE_URL` environment variable from the `app` container. Revision 1 (checkout-67d9799c78) set `DATABASE_URL`, and revision 2 has no env vars. The image is unchanged at python:3.12-alpine, and resources and strategy are unchanged. The deployment now shows desired 1, ready 0, with Available=False (MinimumReplicasUnavailable), even though the new ReplicaSet progressed. I did not check the pod logs, so I can't confirm that the missing variable is what keeps the pod from becoming ready. If it is, restoring `DATABASE_URL` (for example by rolling back to revision 1 or re-adding the variable) would be the fix to consider.

**Evidence**
- `kubernetes_describe_deployment`: checkout rollout_history: revision 2 (checkout-869fc5bcc6, created 36s ago) has env [] and env_from []; revision 1 (checkout-67d9799c78) has env ["DATABASE_URL"]; both use python:3.12-alpine. Replicas desired 1, ready 0; Available=False, MinimumReplicasUnavailable.
- `kubernetes_recent_changes`: checkout revision 2, change "rollout", 48s ago: diff env_removed {"app": ["DATABASE_URL"]}. Revision 1 was created 2m ago with no diff.

**Tool calls**
1. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
2. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 30}
3. `runbooks_read_runbook` {"name": "checkout"} (error)
