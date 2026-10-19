Three workloads in namespace demo are unhealthy, and all three are at 0/1 available (MinimumReplicasUnavailable):

1. **checkout** (python:3.12-alpine): crash loop. The pod exits with code 1 and has restarted 3 times. The container log says `FATAL: required env var DATABASE_URL is not set`, so the likely cause is a missing DATABASE_URL environment variable in the deployment. Adding it, or restoring it from the last good revision, should fix it.

2. **reports** (python:3.12-alpine): OOMKilled crash loop, exit code 137, 3 restarts. The app is loading about 200MB of rows to build the monthly report, which exceeds the container's memory limit. Raising the memory limit or reducing how much data is loaded per run should fix it. I did not inspect the pod's resource limits, so the exact limit is unconfirmed.

3. **frontend** (nginx:1.99.99-does-not-exist): ImagePullBackOff. The image tag does not exist on Docker Hub, so the pod is stuck Pending. Pointing the deployment at a valid tag (for example an existing nginx release) should fix it.

The warning events also show old FailedScheduling events for checkout-67d9799c78-n6mfv and for the earlier reports pod. Those are from previous ReplicaSets, and the only node (aiops-control-plane) has an untolerated taint. They are not the current failure.

**Evidence**
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps (app): 'FATAL: required env var DATABASE_URL is not set' then 'checkout starting, version 1.4.0'; pod status Error exit code 1, 3 restarts
- `kubernetes_pod_logs`: reports-55b4fffc66-hmq7f (app): last log line 'building monthly report: loading 200MB of rows'; container terminated OOMKilled exit code 137, 3 restarts
- `kubernetes_list_pods`: frontend-6f6b4986b9-hxdf2: Pending, 0/1, container web waiting with ErrImagePull, image nginx:1.99.99-does-not-exist not found on docker.io
- `kubernetes_list_deployments`: checkout 0/1, reports 0/1, frontend 0/1; all three report Available=False reason MinimumReplicasUnavailable
- `kubernetes_get_events`: Warning BackOff for checkout pod (restarting failed container app) and reports pod; Warning Failed/ImagePullBackOff for frontend pod with 'not found' pull error; FailedScheduling events for older pods (checkout-67d9799c78-n6mfv, reports-55b4fffc66-hmq7f) due to untolerated taint on the single node

**Tool calls**
1. `kubernetes_list_pods`
2. `kubernetes_list_deployments`
3. `kubernetes_get_events`
4. `kubernetes_pod_logs`
5. `kubernetes_pod_logs`
