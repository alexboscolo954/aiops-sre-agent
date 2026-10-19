The latest rollout, revision 2 (about 48 seconds before the check), removed the `DATABASE_URL` environment variable from the `app` container. Nothing else changed: the image is still `python:3.12-alpine`, and the resource requests and limits are the same. The rollout's ReplicaSet `checkout-869fc5bcc6` progressed, but the deployment now reports 0 of 1 replicas ready, with Available=False (MinimumReplicasUnavailable). Revision 1 had `DATABASE_URL` set. I did not check pod logs, so I can't confirm that the missing variable is why the pod is not ready, but it is the only config change in that rollout. Restoring `DATABASE_URL` to the checkout deployment, or rolling back to revision 1, is the change to consider.

**Evidence**
- `kubernetes_recent_changes`: checkout revision 2 rollout, 48s ago: diff env_removed {app: [DATABASE_URL]}; revision 1 created 2m ago with no diff listed
- `kubernetes_describe_deployment`: checkout app container env: [] (empty), image python:3.12-alpine, requests cpu 10m / memory 32Mi, limit memory 64Mi
- `kubernetes_describe_deployment`: rollout_history revision 1 (checkout-67d9799c78) config app env: [DATABASE_URL], replicas 0; revision 2 (checkout-869fc5bcc6) env: [], replicas 1
- `kubernetes_describe_deployment`: replicas desired 1, ready 0; conditions Available=False reason MinimumReplicasUnavailable; Progressing=True reason NewReplicaSetAvailable

**Tool calls**
1. `kubernetes_describe_deployment`
2. `kubernetes_recent_changes`
