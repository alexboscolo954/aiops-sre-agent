The latest rollout (revision 2, ReplicaSet checkout-869fc5bcc6, about 48 seconds before the check) removed the `DATABASE_URL` environment variable from the `app` container. Revision 1 set `DATABASE_URL`; revision 2 has an empty env list. The image is unchanged (`python:3.12-alpine`), and resource requests and limits are the same. The rollout completed (Progressing=True, NewReplicaSetAvailable), but the deployment reports 0 of 1 replicas ready and Available=False (MinimumReplicasUnavailable). The removed variable is a plausible cause of the unavailability, but I did not check pod logs or events, so that link is not confirmed. To verify, check the checkout pod logs for database connection errors. If the app needs `DATABASE_URL`, restoring it (for example, rolling back to revision 1) would be the fix to consider.

**Evidence**
- `kubernetes_describe_deployment`: checkout revision 2 (ReplicaSet checkout-869fc5bcc6, created 36s ago) has env: [] for app; revision 1 (checkout-67d9799c78) had env: ["DATABASE_URL"]; desired 1, ready 0; Available=False, MinimumReplicasUnavailable
- `kubernetes_recent_changes`: checkout revision 2, change: rollout, diff: env_removed {app: ["DATABASE_URL"]}, 48s ago; revision 1 created 2m ago with no diff

**Tool calls**
1. `kubernetes_describe_deployment`
2. `kubernetes_recent_changes`
