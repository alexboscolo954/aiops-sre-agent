The latest rollout of `checkout` (namespace `demo`) is **revision 2**, ReplicaSet `checkout-869fc5bcc6`, created about 36s before I checked. The only change from revision 1 (`checkout-67d9799c78`) is that **the `DATABASE_URL` env var was removed** from the `app` container. The image is the same in both revisions (`python:3.12-alpine`), and neither revision uses `envFrom`.

**What this broke:** the new pod `checkout-869fc5bcc6-db5ps` is crash-looping. It exits with code 1 (3 restarts so far), and its log says `FATAL: required env var DATABASE_URL is not set`. The deployment has 0 of 1 replicas ready and reports `Available=False` (MinimumReplicasUnavailable). Revision 1 has been scaled down to 0, so no checkout pod is serving.

**Suggested fix (I can only read, so I haven't changed anything):** add `DATABASE_URL` back to the deployment, or roll back with `kubectl rollout undo deployment/checkout -n demo`.

**Evidence**
- `kubernetes_describe_deployment`: checkout rollout_history: rev 2 (checkout-869fc5bcc6, 36s, image python:3.12-alpine) has env []; rev 1 (checkout-67d9799c78, 2m, same image) had env [DATABASE_URL]; ready 0/1, Available=False MinimumReplicasUnavailable
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps Running 0/1, 3 restarts, terminated Error exit_code 1
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'FATAL: required env var DATABASE_URL is not set'

**Tool calls**
1. `kubernetes_describe_deployment` {"cluster": "kind", "name": "checkout", "namespace": "demo"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": "app=checkout"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 30}
