The latest rollout of `checkout` in `demo` is revision 2 (ReplicaSet `checkout-869fc5bcc6`, created about 36s ago). It **removed the `DATABASE_URL` environment variable** from the `app` container. Revision 1 (`checkout-67d9799c78`) had it, and revision 2 has no env vars at all. The image did not change: both revisions use `python:3.12-alpine`.

After this rollout the deployment shows 0 of 1 replicas ready, and its Available condition is False (MinimumReplicasUnavailable). That makes the removed `DATABASE_URL` the likely reason checkout isn't coming up. I haven't confirmed this, because I didn't check the pod logs. If that's the cause, the fix is to put `DATABASE_URL` back or roll back to revision 1.

**Evidence**
- `kubernetes_describe_deployment`: checkout rollout_history: rev 2 (checkout-869fc5bcc6, 36s) env [] vs rev 1 (checkout-67d9799c78, 2m) env [DATABASE_URL]; same image python:3.12-alpine; ready 0/1, Available=False MinimumReplicasUnavailable

**Tool calls**
1. `kubernetes_describe_deployment` {"cluster": "kind", "name": "checkout", "namespace": "demo"}
