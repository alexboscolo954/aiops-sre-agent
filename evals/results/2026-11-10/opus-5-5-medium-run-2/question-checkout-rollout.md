The latest rollout of `checkout` in `demo` is **revision 2** (ReplicaSet `checkout-869fc5bcc6`, created about 36s ago). **Its only change is that it removed the `DATABASE_URL` environment variable** from the `app` container.

- Image is the same in both revisions: `python:3.12-alpine`.
- Revision 1 (`checkout-67d9799c78`) had env `[DATABASE_URL]`. Revision 2 has no env vars and no envFrom.

**What it broke:** the new pod `checkout-869fc5bcc6-db5ps` is crash-looping. It exits with code 1 and has restarted 3 times, and its log says `FATAL: required env var DATABASE_URL is not set`. The deployment now has 0 of 1 replicas ready (`MinimumReplicasUnavailable`). Revision 1 is scaled to 0, so nothing is serving checkout.

**Fix (I can't make changes, so this is a recommendation):** put `DATABASE_URL` back in the deployment spec, or roll back to revision 1 with `kubectl rollout undo deployment/checkout -n demo --to-revision=1`.

**Evidence**
- `kubernetes_describe_deployment`: checkout rollout history: rev 2 (checkout-869fc5bcc6, 36s) env [] vs rev 1 (checkout-67d9799c78, 2m) env [DATABASE_URL]; same image python:3.12-alpine; ready 0/1, Available=False MinimumReplicasUnavailable
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps Running 0/1, 3 restarts, terminated Error exit_code 1
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'FATAL: required env var DATABASE_URL is not set'

**Tool calls**
1. `kubernetes_describe_deployment` {"cluster": "kind", "name": "checkout", "namespace": "demo"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": "app=checkout"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 30}
