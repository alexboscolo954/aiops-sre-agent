Three workloads in demo are unhealthy, all at 0/1 ready:

1. **checkout** (CrashLoopBackOff): Revision 2 was rolled out 48s ago and removed the `DATABASE_URL` env var from container `app`. The app now exits at startup with `FATAL: required env var DATABASE_URL is not set`. Fix: restore `DATABASE_URL` in the checkout deployment, or roll back to revision 1.

2. **reports** (CrashLoopBackOff, OOMKilled, exit 137): The container has a 48Mi memory limit and has been killed 3 times. There was no rollout since it was created, so the limit is likely too low for the workload. Fix: raise the memory limit, then check actual usage.

3. **frontend** (ImagePullBackOff): The image `nginx:1.99.99-does-not-exist` does not exist on docker.io, so the pod is stuck Pending. Fix: point the deployment at a valid tag, such as the previous known-good nginx version.

The reports and frontend pods also show FailedScheduling events from an untolerated node taint, but the pods are now scheduled on aiops-control-plane, so that is not the current blocker.

**Evidence**
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps Running 0/1, restarts 3, last terminated Error exit 1; reports-55b4fffc66-hmq7f Running 0/1, restarts 3, OOMKilled exit 137; frontend-6f6b4986b9-hxdf2 Pending 0/1, ErrImagePull
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps app container: 'FATAL: required env var DATABASE_URL is not set' followed by 'checkout starting, version 1.4.0'
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago: env_removed app: [DATABASE_URL]; revisions 1 of checkout, frontend and reports were created 2m ago with no later changes
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f container app: image python:3.12-alpine, memory limit 48Mi, request 32Mi, state terminated OOMKilled exit 137, restarts 3
- `kubernetes_get_events`: frontend-6f6b4986b9-hxdf2: 'Failed to pull image "nginx:1.99.99-does-not-exist": ... not found' and 'Error: ImagePullBackOff'
- `kubernetes_list_deployments`: checkout, frontend and reports all 0/1 ready with Available=False, reason MinimumReplicasUnavailable

**Tool calls**
1. `kubernetes_list_pods`
2. `kubernetes_list_deployments`
3. `kubernetes_get_events`
4. `kubernetes_pod_logs`
5. `kubernetes_describe_pod`
6. `kubernetes_list_pods`
7. `kubernetes_recent_changes`
