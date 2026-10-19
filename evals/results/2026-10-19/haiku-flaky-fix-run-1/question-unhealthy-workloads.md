Three deployments in namespace demo are unhealthy, all at 0/1 ready with MinimumReplicasUnavailable:

1. **checkout** (CrashLoopBackOff). Revision 2, rolled out about 48s ago, removed the `DATABASE_URL` env var from container `app`. The container exits immediately with `FATAL: required env var DATABASE_URL is not set`, so the restart backoff keeps climbing (3 restarts). Fix: restore `DATABASE_URL` in the checkout deployment, or roll back to revision 1.

2. **reports** (OOMKilled). The container is killed with exit code 137 and has restarted 3 times. Its last log line is `building monthly report: loading 200MB of rows`, so the job loads about 200MB into memory and exceeds its memory limit. I did not read the memory limit from the pod spec, so the exact limit is unconfirmed. Fix: raise the memory limit or reduce how much data the report loads.

3. **frontend** (ImagePullBackOff). The image `nginx:1.99.99-does-not-exist` does not exist on Docker Hub, so the pull fails with NotFound. Fix: point the deployment at a valid nginx tag.

The pods also show FailedScheduling events with 'untolerated taint(s)' on the single node (aiops-control-plane). Those events are from older pod attempts; the current pods are scheduled on that node and running or pending on image pull, so I don't consider the taint a current blocker.

**Evidence**
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps 0/1, restarts 3, last terminated Error exit 1; reports-55b4fffc66-hmq7f 0/1, restarts 3, OOMKilled exit 137; frontend-6f6b4986b9-hxdf2 Pending, waiting ErrImagePull for docker.io/library/nginx:1.99.99-does-not-exist
- `kubernetes_list_deployments`: checkout, frontend and reports all 0/1 ready with Available=False, reason MinimumReplicasUnavailable
- `kubernetes_pod_logs`: checkout pod app container log: 'FATAL: required env var DATABASE_URL is not set' then 'checkout starting, version 1.4.0'
- `kubernetes_pod_logs`: reports pod app container log: 'building monthly report: loading 200MB of rows'
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago with diff env_removed app: [DATABASE_URL]; checkout, frontend and reports revision 1 created about 2m ago
- `kubernetes_get_events`: BackOff restarting failed container app in checkout-869fc5bcc6-db5ps and reports-55b4fffc66-hmq7f; Failed ErrImagePull/ImagePullBackOff for frontend-6f6b4986b9-hxdf2 with 'not found' for nginx:1.99.99-does-not-exist; older FailedScheduling events citing untolerated taint on the single node

**Tool calls**
1. `kubernetes_list_pods`
2. `kubernetes_list_deployments`
3. `kubernetes_get_events`
4. `kubernetes_pod_logs`
5. `kubernetes_pod_logs`
6. `kubernetes_recent_changes`
