Three workloads in namespace demo are unhealthy, all with 0/1 replicas available:

1. **checkout** (python:3.12-alpine) is in CrashLoopBackOff. Its pod exits with code 1 and logs `FATAL: required env var DATABASE_URL is not set`. The cause is revision 2, rolled out about 48s before the check, which removed the `DATABASE_URL` env var from container `app`. Revision 1 had it. Fix: restore `DATABASE_URL` on the checkout deployment (for example with `kubectl set env` or a Helm/GitOps revert), then confirm the rollout.

2. **reports** (python:3.12-alpine) is in CrashLoopBackOff with OOMKilled (exit 137). Its log shows `building monthly report: loading 200MB of rows` just before the kill. The memory limit was not checked, so the cause is probably the container memory limit being too small for that load. Fix: raise the memory limit or reduce how much data the job loads, after checking the pod's limits.

3. **frontend** (nginx:1.99.99-does-not-exist) is stuck in ImagePullBackOff with ErrImagePull. The tag `1.99.99-does-not-exist` is not found on docker.io. Fix: point the deployment at a valid image tag.

All three pods also logged FailedScheduling events earlier (untolerated taints on the single node). Those events are old and the pods are now scheduled on aiops-control-plane, so they are not the current cause.

**Evidence**
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps Running 0/1, 3 restarts, last terminated Error exit_code 1; reports-55b4fffc66-hmq7f Running 0/1, 3 restarts, OOMKilled exit 137; frontend-6f6b4986b9-hxdf2 Pending 0/1, waiting ErrImagePull for nginx:1.99.99-does-not-exist
- `kubernetes_list_deployments`: checkout, frontend and reports all ready 0/1 with Available=False reason MinimumReplicasUnavailable
- `kubernetes_pod_logs`: checkout pod (previous, shown latest instance): 'FATAL: required env var DATABASE_URL is not set' then 'checkout starting, version 1.4.0'
- `kubernetes_pod_logs`: reports pod: 'building monthly report: loading 200MB of rows'
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago with diff env_removed app: [DATABASE_URL]; checkout revision 1 created 2m ago with no diff
- `kubernetes_get_events`: Warning Failed: 'Failed to pull image "nginx:1.99.99-does-not-exist": ... not found' and BackOff events for checkout and reports pods; earlier FailedScheduling for all three pods due to untolerated taint

**Tool calls**
1. `kubernetes_list_pods`
2. `kubernetes_list_deployments`
3. `kubernetes_get_events`
4. `kubernetes_pod_logs`
5. `kubernetes_pod_logs`
6. `kubernetes_recent_changes`
