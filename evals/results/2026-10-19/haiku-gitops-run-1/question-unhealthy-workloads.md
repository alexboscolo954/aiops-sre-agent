Three workloads in namespace demo are unhealthy, each with 0/1 replicas available:

1. **checkout** (`checkout-869fc5bcc6-db5ps`): CrashLoopBackOff, 3 restarts, exit code 1. The previous container log shows `FATAL: required env var DATABASE_URL is not set`. The app exits at startup because DATABASE_URL is missing from its environment.

2. **reports** (`reports-55b4fffc66-hmq7f`): CrashLoopBackOff, 3 restarts, last termination OOMKilled (exit 137). The log shows it was `building monthly report: loading 200MB of rows` when it was killed, so the container's memory limit is too small for that load.

3. **frontend** (`frontend-6f6b4986b9-hxdf2`): Pending, stuck in ErrImagePull/ImagePullBackOff. The image `nginx:1.99.99-does-not-exist` does not exist on Docker Hub, so the pull fails with NotFound.

Fix direction (not applied, read-only investigation): set DATABASE_URL on the checkout deployment, raise reports' memory limit or reduce how much data it loads at once, and point frontend at a valid nginx tag. The events also show old FailedScheduling warnings from the untolerated node taint on the control-plane node, but no pods currently in the list are blocked by it.

**Evidence**
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps Running 0/1, restarts 3, app terminated Error exit 1; reports-55b4fffc66-hmq7f Running 0/1, restarts 3, app terminated OOMKilled exit 137; frontend-6f6b4986b9-hxdf2 Pending 0/1, waiting ErrImagePull
- `kubernetes_list_deployments`: checkout, frontend and reports each ready 0/1 with Available=False reason MinimumReplicasUnavailable
- `kubernetes_pod_logs (checkout, previous)`: "FATAL: required env var DATABASE_URL is not set" followed by "checkout starting, version 1.4.0"
- `kubernetes_pod_logs (reports, previous)`: "building monthly report: loading 200MB of rows" (container then OOMKilled, exit 137)
- `kubernetes_pod_logs / kubernetes_get_events`: frontend pull error: "failed to pull and unpack image docker.io/library/nginx:1.99.99-does-not-exist: not found"; event Failed ErrImagePull and ImagePullBackOff
- `kubernetes_get_events`: BackOff events for checkout (count 4) and reports (count 3); FailedScheduling events for untolerated taint on the single node (aiops-control-plane)

**Tool calls**
1. `kubernetes_list_pods`
2. `kubernetes_list_deployments`
3. `kubernetes_get_events`
4. `kubernetes_pod_logs`
5. `kubernetes_pod_logs`
