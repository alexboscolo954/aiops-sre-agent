The latest rollout of `checkout` in `demo` is revision 2 (ReplicaSet `checkout-869fc5bcc6`). It was created about 36s ago, and revision 1 (`checkout-67d9799c78`) was about 2m old.

**What changed:** the `DATABASE_URL` environment variable was removed from the `app` container. Revision 1 had `env: [DATABASE_URL]` and revision 2 has no env vars. The image did not change: both revisions use `python:3.12-alpine`.

**Current state:** the deployment has 0 of 1 replicas ready and reports `Available=False` (`MinimumReplicasUnavailable`). This started right after the variable was removed, so the missing `DATABASE_URL` is a likely cause. I haven't checked the pod logs to confirm it. If that's the cause, the fix is to put `DATABASE_URL` back or roll back to revision 1.

**Evidence**
- `kubernetes_describe_deployment`: checkout rollout_history: rev 2 (checkout-869fc5bcc6, 36s, python:3.12-alpine, env []) vs rev 1 (checkout-67d9799c78, 2m, python:3.12-alpine, env [DATABASE_URL]); ready 0/1, Available=False MinimumReplicasUnavailable

**Tool calls**
1. `kubernetes_describe_deployment` {"cluster": "kind", "name": "checkout", "namespace": "demo"}
