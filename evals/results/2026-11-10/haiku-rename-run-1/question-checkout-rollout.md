The latest rollout of checkout is revision 2 (ReplicaSet checkout-869fc5bcc6), about 48 seconds old. Its only config change is that the DATABASE_URL environment variable was removed from the app container. Revision 1 (checkout-67d9799c78) had DATABASE_URL set and is now scaled to 0. The image is unchanged at python:3.12-alpine. The rollout completed, but the deployment is not available: desired 1, ready 0, with Available=False (MinimumReplicasUnavailable). Removing DATABASE_URL is the most likely lead for the missing availability, since the app probably needs that variable to start. This is an inference from the diff, not something I confirmed from pod logs. Restoring DATABASE_URL to the checkout deployment, or reverting to revision 1, would be the next step to test.

**Evidence**
- `kubernetes_describe_deployment`: checkout: revision 2 (checkout-869fc5bcc6, 36s old) has env [] and env_from []; revision 1 (checkout-67d9799c78) had env ["DATABASE_URL"] and is now at 0 replicas. Desired 1, ready 0; Available=False, MinimumReplicasUnavailable; Progressing=True, NewReplicaSetAvailable.
- `kubernetes_recent_changes`: demo/checkout revision 2 rollout 48s ago with diff env_removed {"app": ["DATABASE_URL"]}; image unchanged.

**Tool calls**
1. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
2. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 1440}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 1440}
