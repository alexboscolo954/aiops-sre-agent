The latest rollout (revision 2, ReplicaSet checkout-869fc5bcc6, about 48 seconds before the check) removed the DATABASE_URL environment variable from the app container. The image stayed python:3.12-alpine, and no env_from sources were added. Revision 1 had DATABASE_URL set. The deployment now has 0 of 1 replicas ready, with Available=False (MinimumReplicasUnavailable), so the removed variable is a likely cause of the outage. I did not check pod logs to confirm that.

**Evidence**
- `kubernetes_recent_changes`: checkout revision 2 (change: rollout, 48s ago) with diff env_removed: {"app": ["DATABASE_URL"]}; revision 1 was created 2m ago with no diff.
- `kubernetes_describe_deployment`: checkout app container env is empty ([]) and env_from is empty; rollout_history revision 2 (checkout-869fc5bcc6) config env [] vs revision 1 (checkout-67d9799c78) env ["DATABASE_URL"]; both revisions use python:3.12-alpine.
- `kubernetes_describe_deployment`: replicas desired 1, ready 0; condition Available=False reason MinimumReplicasUnavailable, while Progressing=True reason NewReplicaSetAvailable.

**Tool calls**
1. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
2. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
