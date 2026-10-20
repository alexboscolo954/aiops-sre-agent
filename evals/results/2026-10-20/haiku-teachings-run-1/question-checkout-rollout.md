The latest rollout (revision 2, ReplicaSet checkout-869fc5bcc6, about 48 seconds old) removed the `DATABASE_URL` environment variable from the `app` container. Nothing else changed: the image is still `python:3.12-alpine` and resource settings are the same. Revision 1 had `DATABASE_URL` set, and revision 2 has an empty env list. The deployment is now at 0 of 1 replicas ready, with Available=False (MinimumReplicasUnavailable), so the missing variable may be related, but I did not check the pod logs to confirm that.

**Evidence**
- `kubernetes_recent_changes`: checkout revision 2, change 'rollout', 48s ago: diff env_removed {app: [DATABASE_URL]}; revision 1 was 'created' 2m ago with no diff.
- `kubernetes_describe_deployment`: checkout rollout_history: revision 2 (checkout-869fc5bcc6) env [] and image python:3.12-alpine; revision 1 (checkout-67d9799c78) env [DATABASE_URL], replicas 0. Current env is empty and replicas desired 1, ready 0.
- `kubernetes_describe_deployment`: checkout conditions: Progressing=True (NewReplicaSetAvailable), Available=False (MinimumReplicasUnavailable: Deployment does not have minimum availability).

**Tool calls**
1. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
2. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 1440}
