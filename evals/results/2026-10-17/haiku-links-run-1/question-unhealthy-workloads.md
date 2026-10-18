Three of the four pods in namespace demo are unhealthy, across three deployments. `checkout` is the only one with a working replica, and that replica is 1/1 ready.

- **frontend** (0/1 ready): The image `nginx:1.99.99-does-not-exist` does not exist, so the pull fails with ErrImagePull, then ImagePullBackOff. The deployment reports MinimumReplicasUnavailable. Fix: point the deployment at a valid nginx tag.
- **checkout** (new pod 0/1 ready, 2 restarts): The app exits with code 1 at startup with `FATAL: required env var DATABASE_URL is not set`. The pod is in BackOff. The older replica pwjtr is still 1/1 Running, so the rollout is stuck on the new pod. Fix: add the DATABASE_URL env var to the deployment, for example from a Secret or ConfigMap.
- **reports** (0/1 ready, 2 restarts): The container was terminated with OOMKilled (exit 137) and is in BackOff. The deployment reports MinimumReplicasUnavailable. I did not read its logs. Fix: raise the memory limit or investigate the memory usage.

**Evidence**
- `kubernetes_list_pods`: frontend-79765fc9d-pqg7h Pending, 0/1, container web waiting with ErrImagePull for docker.io/library/nginx:1.99.99-does-not-exist (not found)
- `kubernetes_list_pods`: checkout-7c856f898c-bjtfx Running 0/1, 2 restarts, app last terminated Error exit code 1; checkout-7784c7f885-pwjtr Running 1/1, 0 restarts
- `kubernetes_list_pods`: reports-7cc9978bbf-sq7r7 Running 0/1, 2 restarts, app terminated OOMKilled exit code 137
- `kubernetes_list_deployments`: frontend 0/1 and reports 0/1 both show Available MinimumReplicasUnavailable; checkout 1/1 with no problems
- `kubernetes_get_events`: Warning Failed/ErrImagePull/ImagePullBackOff on Pod/frontend-79765fc9d-pqg7h; BackOff restarting failed container app on checkout-7c856f898c-bjtfx and reports-7cc9978bbf-sq7r7
- `kubernetes_pod_logs`: checkout-7c856f898c-bjtfx app: 'checkout starting, version 1.4.0' then 'FATAL: required env var DATABASE_URL is not set'

**Tool calls**
1. `kubernetes_list_pods`
2. `kubernetes_list_deployments`
3. `kubernetes_get_events`
4. `kubernetes_pod_logs`
