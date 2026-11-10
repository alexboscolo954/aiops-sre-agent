The latest checkout rollout (revision 2, ReplicaSet checkout-869fc5bcc6, about 36–48 seconds old) removed the `DATABASE_URL` environment variable from the `app` container. Nothing else changed: the image stayed `python:3.12-alpine`, and no env_from entries or resource settings are listed in the diff.

Effect: the deployment now has 0 of 1 replicas ready and Available=False ("MinimumReplicasUnavailable"), although Progressing=True reports the new ReplicaSet as having progressed. The removal is the most likely cause of the unavailability, but I did not check the pod logs to confirm that the app fails without `DATABASE_URL`.

Suggested fix: restore `DATABASE_URL` on the checkout deployment (for example, by rolling back to revision 1 with `kubectl rollout undo deployment/checkout -n demo`, or by re-adding the variable).

**Evidence**
- `kubernetes_recent_changes`: checkout revision 2 (48s ago) change 'rollout' with diff env_removed: {app: [DATABASE_URL]}; revision 1 was created 2m ago with no diff.
- `kubernetes_describe_deployment`: checkout: desired 1, ready 0; Available=False reason MinimumReplicasUnavailable; Progressing=True NewReplicaSetAvailable; revision 2 (checkout-869fc5bcc6) env [] vs revision 1 (checkout-67d9799c78) env [DATABASE_URL]; image python:3.12-alpine in both.

**Tool calls**
1. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
2. `kubernetes_recent_changes` {"cluster": "kind"}
3. `Answer` {"answer": "The latest checkout rollout (revision 2, ReplicaSet checkout-869fc5bcc6, about 36\u201348 seconds old) removed the `DATABASE_URL` environment variable from the `app` container. Nothing else changed: the image stayed `python:3.12-alpine`, and no env_from entries or resource settings are l
