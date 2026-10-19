The latest rollout, revision 2 (ReplicaSet checkout-869fc5bcc6, about 48 seconds old), removed the DATABASE_URL environment variable from the app container. The image did not change and still uses python:3.12-alpine. Revision 1 (checkout-67d9799c78) had DATABASE_URL set and is now scaled to 0. The deployment is now unavailable with 0 of 1 desired replicas ready (Available=False, MinimumReplicasUnavailable), so the missing variable is a likely cause. I did not check the pod logs, so that link is unconfirmed. Restoring DATABASE_URL to the checkout deployment is the likely fix; that is a change for you to make.

**Evidence**
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago: diff env_removed {app: [DATABASE_URL]}; revision 1 created 2m ago with no diff.
- `kubernetes_describe_deployment`: checkout container app: image python:3.12-alpine, env: [] (empty) on revision 2; revision 1 config env: [DATABASE_URL].
- `kubernetes_describe_deployment`: checkout replicas desired 1, ready 0; Available=False reason MinimumReplicasUnavailable; Progressing=True NewReplicaSetAvailable.

**Tool calls**
1. `kubernetes_describe_deployment`
2. `kubernetes_recent_changes`
