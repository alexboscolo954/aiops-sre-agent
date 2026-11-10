The latest rollout is **revision 2** (ReplicaSet `checkout-869fc5bcc6`, about 36s old). Its only change from revision 1 (`checkout-67d9799c78`, about 2m old) is that **the `DATABASE_URL` env var was removed** from the `app` container. The image is still `python:3.12-alpine` in both revisions, and the env list went from `["DATABASE_URL"]` to `[]`.

**What that broke:** the new pod `checkout-869fc5bcc6-db5ps` exits with code 1 and has restarted 3 times. Its log shows `FATAL: required env var DATABASE_URL is not set`. The deployment has 0 of 1 replicas ready, and its Available condition is False (MinimumReplicasUnavailable). Revision 1 has been scaled to 0, so checkout is currently down.

**Suggested fix:** put `DATABASE_URL` back in the deployment spec, or roll back to revision 1 (`kubectl rollout undo deployment/checkout -n demo`). I only have read access, so someone else will need to make the change.

**Evidence**
- `kubernetes_describe_deployment`: checkout rollout_history: rev 2 (checkout-869fc5bcc6, 36s) env [] vs rev 1 (checkout-67d9799c78, 2m) env ["DATABASE_URL"]; image python:3.12-alpine in both; ready 0/1, Available=False MinimumReplicasUnavailable
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps Running 0/1, 3 restarts, terminated Error exit_code 1
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'FATAL: required env var DATABASE_URL is not set'

**Tool calls**
1. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": "app=checkout"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 50}
