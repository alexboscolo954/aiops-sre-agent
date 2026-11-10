**The latest rollout (revision 2, ReplicaSet `checkout-869fc5bcc6`, about 48s ago) removed the `DATABASE_URL` env var from the `app` container. Nothing else changed.** The image is still `python:3.12-alpine` and resources are the same (requests 10m CPU / 32Mi, limit 64Mi). Revision 1 (`checkout-67d9799c78`) had `DATABASE_URL`; revision 2 has no env vars.

**What it broke:** The new pod `checkout-869fc5bcc6-db5ps` is crash-looping. It exits with code 1 and has restarted 3 times, and its log says `FATAL: required env var DATABASE_URL is not set`. The deployment shows 0/1 ready, with `Available=False` (MinimumReplicasUnavailable). The old ReplicaSet is scaled to 0, so checkout is fully down right now.

**Recommended fix (I can only read, so I haven't changed anything):** Add `DATABASE_URL` back to the deployment, or roll back to revision 1 with `kubectl rollout undo deployment/checkout -n demo`.

Other pods in `demo` are failing too, but not because of this change:
- `frontend` can't pull image `nginx:1.99.99-does-not-exist` (ErrImagePull).
- `reports` is being OOMKilled.

Neither was changed after it was created.

**Evidence**
- `kubernetes_describe_deployment`: checkout rollout_history: rev 2 (checkout-869fc5bcc6, 36s, 1 replica) env [] vs rev 1 (checkout-67d9799c78, 0 replicas) env [DATABASE_URL]; same image python:3.12-alpine; ready 0/1, Available=False MinimumReplicasUnavailable
- `kubernetes_recent_changes`: 48s ago demo/checkout revision 2 rollout, diff: env_removed {app: [DATABASE_URL]}; frontend and reports only created, no changes since
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps 0/1 ready, 3 restarts, terminated Error exit_code 1; frontend ErrImagePull; reports OOMKilled
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'FATAL: required env var DATABASE_URL is not set'

**Tool calls**
1. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
2. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
3. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": "app=checkout"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 30}
