Three workloads in namespace `demo` are unhealthy (all 0/1 available). Each has a different cause:

1. **checkout** (pod `checkout-869fc5bcc6-db5ps`, CrashLoopBackOff-style restarts, 3 restarts): the rollout to revision 2 removed the `DATABASE_URL` env var from container `app`. The app exits at startup with `FATAL: required env var DATABASE_URL is not set`. Fix: restore `DATABASE_URL` in the checkout deployment (or roll back to revision 1).

2. **frontend** (pod `frontend-6f6b4986b9-hxdf2`, Pending): the image `nginx:1.99.99-does-not-exist` does not exist, so the pull fails with `ErrImagePull` / `NotFound`. Fix: correct the image tag to a real version and roll out again.

3. **reports** (pod `reports-55b4fffc66-hmq7f`, 3 restarts): the container is `OOMKilled` (exit 137). Its memory limit is only 48Mi. Fix: raise the memory limit (the request is 32Mi). The pod also earlier logged a FailedScheduling taint event, and the image pull took about 1m21s, but the current failure is the OOM kill.

No env or image changes are recorded for reports and frontend since their initial creation. The only recent change in the namespace is the checkout rollout (revision 2, 48s before the check).

**Evidence**
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps 0/1, 3 restarts, last terminated Error exit 1; frontend-6f6b4986b9-hxdf2 Pending, waiting ErrImagePull for nginx:1.99.99-does-not-exist; reports-55b4fffc66-hmq7f 0/1, 3 restarts, OOMKilled exit 137.
- `kubernetes_list_deployments`: checkout, frontend and reports each 0/1 ready with MinimumReplicasUnavailable.
- `kubernetes_pod_logs`: checkout previous logs: 'FATAL: required env var DATABASE_URL is not set' then 'checkout starting, version 1.4.0'.
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f: container app terminated OOMKilled exit 137, memory limit 48Mi, request 32Mi, restarts 3; Back-off restarting failed container event; earlier FailedScheduling taint event.
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago with diff env_removed app: [DATABASE_URL]; checkout, frontend and reports revision 1 created 2m ago with no other diffs.

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true}
4. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
5. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
6. `Answer` {"answer": "Three workloads in namespace `demo` are unhealthy (all 0/1 available). Each has a different cause:\n\n1. **checkout** (pod `checkout-869fc5bcc6-db5ps`, CrashLoopBackOff-style restarts, 3 restarts): the rollout to revision 2 removed the `DATABASE_URL` env var from container `app`. The app
