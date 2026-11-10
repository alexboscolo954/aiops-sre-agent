The latest rollout of `checkout` (revision 2, ReplicaSet `checkout-869fc5bcc6`, about 48s old) removed the `DATABASE_URL` env var from the `app` container. Nothing else changed. The image is still `python:3.12-alpine`, and the resources are the same.

The rollout has broken the service. The new pod `checkout-869fc5bcc6-db5ps` is 0/1 ready and has restarted 3 times, exiting with code 1. Its log says `FATAL: required env var DATABASE_URL is not set`. The deployment shows Available=False (MinimumReplicasUnavailable). Revision 1 (`checkout-67d9799c78`) had `DATABASE_URL` set and is now scaled to 0.

**Recommendation:** restore `DATABASE_URL` in the deployment spec, or roll back to revision 1. I can't change anything with my read-only tools. I also couldn't see how revision 1 supplied the value, so check that before restoring it.

**Evidence**
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago; diff: env_removed {app: [DATABASE_URL]}
- `kubernetes_describe_deployment`: Revision 2 (checkout-869fc5bcc6) has no env vars, image python:3.12-alpine. Revision 1 had DATABASE_URL and is scaled to 0. Ready 0/1, Available=False.
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps is 0/1 ready, 3 restarts, last terminated with Error exit code 1
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'FATAL: required env var DATABASE_URL is not set'

**Tool calls**
1. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
2. `kubernetes_recent_changes` {"cluster": "kind"}
3. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": "app=checkout"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 20}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 1}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 5}
