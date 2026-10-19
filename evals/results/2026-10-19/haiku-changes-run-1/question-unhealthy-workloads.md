Three deployments in namespace demo are unhealthy, each at 0/1 ready with MinimumReplicasUnavailable:

1. **checkout** (python:3.12-alpine) is in CrashLoopBackOff with exit code 1. The app logs `FATAL: required env var DATABASE_URL is not set`, so the pod is missing the DATABASE_URL environment variable. Fix by setting it on the deployment, for example from a Secret or ConfigMap.

2. **reports** (python:3.12-alpine) is in CrashLoopBackOff with OOMKilled (exit 137). It was loading about 200MB of rows for the monthly report when it was killed. Raise the container's memory limit or reduce how much data it loads at once.

3. **frontend** is stuck in Pending/ImagePullBackOff. The image `nginx:1.99.99-does-not-exist` does not exist on Docker Hub. Point the deployment at a valid tag, such as an existing nginx release.

Separately, an older checkout ReplicaSet pod (checkout-67d9799c78-n6mfv) and the reports and frontend pods each logged FailedScheduling because the only node has an untolerated taint. That warning is from the earlier scheduling attempts and does not show in the current pod list. I did not check the node taints further.

**Evidence**
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps: 0/1 ready, 3 restarts, last terminated Error exit 1; reports-55b4fffc66-hmq7f: 0/1 ready, 3 restarts, OOMKilled exit 137; frontend-6f6b4986b9-hxdf2: Pending, 0/1 ready, waiting ErrImagePull
- `kubernetes_list_deployments`: checkout, frontend and reports all at 0/1 ready with Available=False, reason MinimumReplicasUnavailable
- `kubernetes_pod_logs (checkout-869fc5bcc6-db5ps)`: "FATAL: required env var DATABASE_URL is not set" followed by "checkout starting, version 1.4.0"
- `kubernetes_pod_logs (reports-55b4fffc66-hmq7f)`: "building monthly report: loading 200MB of rows" before the container was OOMKilled
- `kubernetes_get_events`: frontend-6f6b4986b9-hxdf2: "Failed to pull image nginx:1.99.99-does-not-exist ... not found", Error: ImagePullBackOff
- `kubernetes_get_events`: BackOff events on checkout-869fc5bcc6-db5ps ("Back-off restarting failed container app") and reports-55b4fffc66-hmq7f; FailedScheduling on checkout-67d9799c78-n6mfv, frontend and reports: "1 node(s) had untolerated taint(s)"

**Tool calls**
1. `kubernetes_list_pods`
2. `kubernetes_list_deployments`
3. `kubernetes_get_events`
4. `kubernetes_pod_logs`
5. `kubernetes_pod_logs`
