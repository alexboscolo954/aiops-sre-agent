The latest rollout of `checkout` (revision 2, ReplicaSet `checkout-869fc5bcc6`) removed the `DATABASE_URL` env var from the `app` container. Nothing else changed. The image is still `python:3.12-alpine`, and the resources and other config are the same.

The rollout broke the deployment:
- The new pod `checkout-869fc5bcc6-db5ps` is at 0/1 ready and has restarted 3 times. It exits with code 1.
- Its log says `FATAL: required env var DATABASE_URL is not set`.
- The deployment shows 0 of 1 replicas ready and `Available=False` (`MinimumReplicasUnavailable`).
- Revision 1 (`checkout-67d9799c78`) had `DATABASE_URL` set and is scaled to 0, so nothing is serving.

Recommended fix: restore `DATABASE_URL` in the deployment, or roll back to revision 1 (`kubectl rollout undo deployment/checkout -n demo`). The tools I have are read-only, so I haven't changed anything.

**Evidence**
- `kubernetes_recent_changes`: demo/checkout revision 2 rollout 48s ago; diff: env_removed app: [DATABASE_URL]
- `kubernetes_describe_deployment`: Revision 2 (checkout-869fc5bcc6) has env [] with the same image python:3.12-alpine. Revision 1 had env DATABASE_URL and is scaled to 0. Ready 0/1, Available=False.
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps is 0/1 ready with 3 restarts, terminated with Error, exit code 1
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps logs: 'FATAL: required env var DATABASE_URL is not set' (checkout version 1.4.0)

**Tool calls**
1. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
2. `kubernetes_recent_changes` {"cluster": "kind"}
3. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": "app=checkout"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 20}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 5, "previous": true}
