Three workloads in `demo` are unhealthy (cluster `kind`):

1. **frontend** (0/1 ready). Its pod is stuck in `ErrImagePull`/`ImagePullBackOff`. The deployment points at the image `nginx:1.99.99-does-not-exist`, and that tag doesn't exist on Docker Hub. Fix: set a valid nginx tag, or roll back.

2. **checkout** (the deployment shows 1/1, but the new revision is failing). Pod `checkout-7c856f898c-bjtfx` is crash-looping with exit code 1. Its log says `FATAL: required env var DATABASE_URL is not set`. Revision 2 dropped the `DATABASE_URL` env var that revision 1 had. The old revision 1 pod, `checkout-7784c7f885-pwjtr`, is still running, so the deployment still reports available. Fix: restore `DATABASE_URL` in the deployment spec, or roll back to revision 1.

3. **reports** (0/1 ready). The pod is `OOMKilled` (exit 137) and has restarted repeatedly. Its memory limit is only 48Mi. Fix: raise the memory limit, and check the app's memory use. I did not read the app's logs or check what it actually needs.

**Evidence**
- `kubernetes_list_pods`: frontend-79765fc9d-pqg7h Pending, ErrImagePull: docker.io/library/nginx:1.99.99-does-not-exist not found
- `kubernetes_list_deployments`: frontend 0/1 and reports 0/1 with MinimumReplicasUnavailable; checkout 1/1
- `kubernetes_pod_logs`: checkout-7c856f898c-bjtfx: 'FATAL: required env var DATABASE_URL is not set'
- `kubernetes_describe_deployment`: checkout revision 2 has env [] while revision 1 had DATABASE_URL; the revision 1 pod is still running
- `kubernetes_describe_pod`: reports-7cc9978bbf-sq7r7 terminated OOMKilled exit 137, memory limit 48Mi, 2 restarts
- `kubernetes_get_events`: BackOff warnings for checkout and reports pods; Failed/ImagePullBackOff for frontend

**Tool calls**
1. `kubernetes_list_pods`
2. `kubernetes_list_deployments`
3. `kubernetes_get_events`
4. `kubernetes_pod_logs`
5. `kubernetes_describe_deployment`
6. `kubernetes_describe_pod`
