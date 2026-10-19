Three workloads in namespace demo are unhealthy, each for a different reason. All three are at 0/1 ready with MinimumReplicasUnavailable.

1. **checkout** (pod checkout-869fc5bcc6-db5ps): CrashLoopBackOff, 3 restarts, exit code 1. The app exits at startup with `FATAL: required env var DATABASE_URL is not set`. Revision 1 (checkout-67d9799c78) had `DATABASE_URL` in its env; the current revision 2 (checkout-869fc5bcc6, created about 36s before the check) has no env vars. The rollout dropped the variable, so this is most likely the cause. Fix: restore `DATABASE_URL` (for example from the Secret or ConfigMap revision 1 used) or roll back to revision 1.

2. **frontend** (pod frontend-6f6b4986b9-hxdf2): ImagePullBackOff. The image `nginx:1.99.99-does-not-exist` cannot be resolved on docker.io (NotFound). Fix: correct the image tag to one that exists and roll out again.

3. **reports** (pod reports-55b4fffc66-hmq7f): OOMKilled, exit code 137, 3 restarts. The container's memory limit is 48Mi (request 32Mi). Fix: raise the memory limit, then check whether the workload still gets OOMKilled.

The earlier FailedScheduling events (untolerated taint) are historical; the pods are now scheduled on aiops-control-plane.

**Evidence**
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps Running 0/1, restarts 3, last terminated Error exit 1; frontend-6f6b4986b9-hxdf2 Pending 0/1, waiting ErrImagePull; reports-55b4fffc66-hmq7f Running 0/1, restarts 3, terminated OOMKilled exit 137
- `kubernetes_list_deployments`: checkout, frontend and reports all 0/1 ready with Available=False, reason MinimumReplicasUnavailable
- `kubernetes_pod_logs`: checkout previous/latest logs: 'FATAL: required env var DATABASE_URL is not set' then 'checkout starting, version 1.4.0'
- `kubernetes_describe_deployment`: checkout rollout_history: revision 2 (checkout-869fc5bcc6, 36s old) config env: [] ; revision 1 (checkout-67d9799c78) config env: [DATABASE_URL]
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f container app: state terminated OOMKilled exit 137, restarts 3, limits memory 48Mi, requests memory 32Mi
- `kubernetes_get_events`: frontend: 'Failed to pull image "nginx:1.99.99-does-not-exist": ... not found' and 'Error: ImagePullBackOff'; checkout and reports: 'Back-off restarting failed container app'

**Tool calls**
1. `kubernetes_list_pods`
2. `kubernetes_list_deployments`
3. `kubernetes_get_events`
4. `kubernetes_pod_logs`
5. `kubernetes_describe_pod`
6. `kubernetes_describe_deployment`
