**What changed:** the latest rollout, revision 2 (ReplicaSet `checkout-869fc5bcc6`, created about 36s ago), removed the **`DATABASE_URL` environment variable** from the `app` container. Revision 1 (`checkout-67d9799c78`, about 2m old) had `env: [DATABASE_URL]`. Revision 2 has `env: []`.

**What stayed the same:** the image is still `python:3.12-alpine` in both revisions. The deployment's current resources are 10m CPU and 32Mi memory requested, with a 64Mi memory limit. The rollout history only compares images and env var names, so I can't confirm whether resources changed too.

**Current state:** the deployment shows 0 of 1 replicas ready and `Available=False` (`MinimumReplicasUnavailable`). Revision 1 has already been scaled down to 0. I didn't check the pod logs, so I haven't confirmed that the missing `DATABASE_URL` is why the pod isn't ready, but it is the only change I could see. If checkout needs that variable, I recommend adding it back or rolling back to revision 1 (`kubectl rollout undo deployment/checkout -n demo --to-revision=1`).

**Evidence**
- `kubernetes_describe_deployment`: checkout rollout_history: revision 2 (checkout-869fc5bcc6, 36s) env [] image python:3.12-alpine; revision 1 (checkout-67d9799c78, 2m) env [DATABASE_URL], same image
- `kubernetes_describe_deployment`: checkout replicas desired 1 / ready 0; condition Available=False, reason MinimumReplicasUnavailable

**Tool calls**
1. `kubernetes_describe_deployment` {"cluster": "kind", "name": "checkout", "namespace": "demo"}
