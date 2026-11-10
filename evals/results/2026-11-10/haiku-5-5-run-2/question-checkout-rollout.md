The latest checkout rollout (revision 2, ReplicaSet checkout-869fc5bcc6, about 36–48 seconds old) removed the `DATABASE_URL` environment variable from the `app` container. Nothing else changed: the image is still `python:3.12-alpine` and resource requests/limits are unchanged. Revision 1 (checkout-67d9799c78) had `DATABASE_URL` set and is now scaled to 0.

This likely matters: the checkout deployment now shows 0 of 1 replicas ready, with Available=False (MinimumReplicasUnavailable). The rollout itself progressed, so the missing variable is the most likely lead for the unavailability, but I did not check pod logs to confirm that the app fails without it. Suggested next step: check the checkout pod logs, and if the app needs `DATABASE_URL`, roll back to revision 1 (`kubectl rollout undo deployment/checkout -n demo`) or restore the variable.

**Evidence**
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago: diff env_removed {"app": ["DATABASE_URL"]}; revision 1 created 2m ago with no diff.
- `kubernetes_describe_deployment`: checkout: image python:3.12-alpine, env [] for app; revision 2 (checkout-869fc5bcc6) has env [], revision 1 (checkout-67d9799c78) had env ["DATABASE_URL"] and 0 replicas; desired 1, ready 0; Available=False MinimumReplicasUnavailable, Progressing=True NewReplicaSetAvailable.

**Tool calls**
1. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
2. `kubernetes_recent_changes` {"cluster": "kind"}
3. `Answer` {"answer": "The latest checkout rollout (revision 2, ReplicaSet checkout-869fc5bcc6, about 36\u201348 seconds old) removed the `DATABASE_URL` environment variable from the `app` container. Nothing else changed: the image is still `python:3.12-alpine` and resource requests/limits are unchanged. Revis
