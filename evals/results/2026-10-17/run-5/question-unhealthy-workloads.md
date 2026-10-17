All three deployments in `demo` are unhealthy, each for a different reason:

1. **frontend** (0/1, pod `frontend-79765fc9d-pqg7h`, Pending): `ErrImagePull` / `ImagePullBackOff`. The image `nginx:1.99.99-does-not-exist` doesn't exist in the registry. Fix: set the deployment to a valid nginx tag, or roll back.

2. **checkout** (new pod `checkout-7c856f898c-bjtfx`, 0/1, crash-looping with exit code 1): the logs say `FATAL: required env var DATABASE_URL is not set`. Revision 2 of the deployment dropped the `DATABASE_URL` env var that revision 1 had. The old revision 1 pod (`checkout-7784c7f885-pwjtr`) is still Running 1/1, so the deployment reports Available. The rollout is stuck. Fix: restore `DATABASE_URL` in the pod spec, or roll back to revision 1.

3. **reports** (pod `reports-7cc9978bbf-sq7r7`, 0/1, restarted 2 times): `OOMKilled` with exit code 137. The memory limit is 48Mi, and the app logs `building monthly report: loading 200MB of rows`. That is far more than the limit. I couldn't check actual memory usage because I have no metrics tool. Fix, following the oom-killed runbook: raise the memory limit and request well above the real peak plus 25%, or change the report to stream or paginate instead of loading all rows at once.

**Evidence**
- `kubernetes_list_pods`: frontend-79765fc9d-pqg7h Pending, web waiting ErrImagePull: nginx:1.99.99-does-not-exist not found
- `kubernetes_get_events`: frontend: Failed to pull image / ErrImagePull / ImagePullBackOff; checkout and reports: BackOff restarting failed container
- `kubernetes_pod_logs`: checkout-7c856f898c-bjtfx: 'FATAL: required env var DATABASE_URL is not set'
- `kubernetes_describe_deployment`: checkout revision 2 (checkout-7c856f898c) has no env vars; revision 1 (checkout-7784c7f885) had DATABASE_URL
- `kubernetes_describe_pod`: reports container limit memory 48Mi, last state OOMKilled exit 137, restarts 2
- `kubernetes_pod_logs`: reports: 'building monthly report: loading 200MB of rows'
- `runbooks_read_runbook`: oom-killed: raise limit to observed peak +25% or fix the leak; restarting only buys time

**Tool calls**
1. `kubernetes_list_pods`
2. `kubernetes_list_deployments`
3. `kubernetes_pod_logs`
4. `kubernetes_describe_deployment`
5. `kubernetes_describe_pod`
6. `kubernetes_pod_logs`
7. `runbooks_search_runbooks`
8. `runbooks_read_runbook`
9. `kubernetes_get_events`
