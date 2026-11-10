**The latest rollout (revision 2, ReplicaSet `checkout-869fc5bcc6`, created about 36s ago) removed the `DATABASE_URL` environment variable from the `app` container.** Nothing else changed: the image is still `python:3.12-alpine` in both revisions. Revision 1 (`checkout-67d9799c78`) had `env: [DATABASE_URL]`, and revision 2 has `env: []`.

**What it broke:** checkout is down, with 0 of 1 replicas ready and the deployment showing `Available=False`. The new pod `checkout-869fc5bcc6-db5ps` exits with code 1 and has restarted 3 times. Its log says `FATAL: required env var DATABASE_URL is not set`.

**Suggested fix (I can't make changes):** put `DATABASE_URL` back in the deployment spec, or roll back to revision 1 with `kubectl rollout undo deployment/checkout -n demo --to-revision=1`.

**Evidence**
- `kubernetes_describe_deployment`: checkout rollout history: rev 2 (checkout-869fc5bcc6, 36s) image python:3.12-alpine, env []; rev 1 (checkout-67d9799c78, 2m) image python:3.12-alpine, env [DATABASE_URL]; ready 0/1, Available=False MinimumReplicasUnavailable
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps: ready 0/1, 3 restarts, terminated Error exit_code 1
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'FATAL: required env var DATABASE_URL is not set'

**Tool calls**
1. `kubernetes_describe_deployment` {"cluster": "kind", "name": "checkout", "namespace": "demo"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": "app=checkout"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 30}
