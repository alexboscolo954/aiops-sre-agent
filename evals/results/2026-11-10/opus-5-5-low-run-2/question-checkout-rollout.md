The latest rollout is **revision 2** (ReplicaSet `checkout-869fc5bcc6`, created about 36s ago). It **removed the `DATABASE_URL` environment variable** from the `app` container. Revision 1 (`checkout-67d9799c78`) had that variable, and revision 2 has no env vars. The image did not change: both revisions use `python:3.12-alpine`.

Since this rollout, the deployment shows 0 of 1 replicas ready and `Available=False` (MinimumReplicasUnavailable). The missing `DATABASE_URL` is a likely cause, but I haven't checked the pod logs to confirm it. If it is the cause, the fix is to put `DATABASE_URL` back or roll back to revision 1.

**Evidence**
- `kubernetes_describe_deployment`: checkout rollout_history: rev 2 (checkout-869fc5bcc6, 36s) env [] vs rev 1 (checkout-67d9799c78, 2m) env [DATABASE_URL]; both image python:3.12-alpine; ready 0/1, Available=False

**Tool calls**
1. `kubernetes_describe_deployment` {"cluster": "kind", "name": "checkout", "namespace": "demo"}
