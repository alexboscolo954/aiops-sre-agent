The checkout deployment's latest rollout (revision 2, ReplicaSet checkout-869fc5bcc6, about 48s before the check) removed the `DATABASE_URL` environment variable from the `app` container. Revision 1 set `DATABASE_URL`; revision 2 has no env vars at all. The image did not change (python:3.12-alpine in both).

As a result, the new pod crashes on startup with `FATAL: required env var DATABASE_URL is not set`. It is in CrashLoopBackOff-style restarts (3 restarts, exit code 1), 0/1 ready, and the deployment is not Available (`MinimumReplicasUnavailable`). The old revision-1 ReplicaSet is scaled to 0, so checkout has no serving pods.

Fix: restore `DATABASE_URL` on the checkout deployment (for example, roll back to revision 1 with `kubectl rollout undo`, or re-add the env var from its original source). I have not made any change.

Other items in the same namespace, not part of checkout: frontend is stuck in ErrImagePull for `nginx:1.99.99-does-not-exist`, and reports is OOMKilled (exit 137) with 3 restarts.

**Evidence**
- `kubernetes_describe_deployment`: checkout: revision 2 (checkout-869fc5bcc6, 36s old) has config app env: [] and image python:3.12-alpine; revision 1 (checkout-67d9799c78) had env [DATABASE_URL] and is scaled to 0. Available=False, MinimumReplicasUnavailable.
- `kubernetes_recent_changes`: demo/checkout revision 2 rollout, 48s ago: diff env_removed {app: [DATABASE_URL]}.
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps: 0/1 ready, restarts 3, last terminated Error exit code 1.
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps previous logs: 'FATAL: required env var DATABASE_URL is not set' followed by 'checkout starting, version 1.4.0'.

**Tool calls**
1. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
2. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 1440}
3. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": "app=checkout"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 30}
5. `Answer` {"answer": "The checkout deployment's latest rollout (revision 2, ReplicaSet checkout-869fc5bcc6, about 48s before the check) removed the `DATABASE_URL` environment variable from the `app` container. Revision 1 set `DATABASE_URL`; revision 2 has no env vars at all. The image did not change (python:3
