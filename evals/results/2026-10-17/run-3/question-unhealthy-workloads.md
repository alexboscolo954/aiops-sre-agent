Three workloads in `demo` are unhealthy. Each has a different cause:

1. **frontend** (0/1, pod Pending). The image `nginx:1.99.99-does-not-exist` doesn't exist, so the pod is stuck in ErrImagePull/ImagePullBackOff. Fix: set the deployment to a valid nginx tag, or roll back.
2. **checkout** (rollout in progress, new pod crash-looping). Revision 2 (`checkout-7c856f898c`) dropped the `DATABASE_URL` env var that revision 1 had. The new pod exits with code 1 and logs `FATAL: required env var DATABASE_URL is not set`. The old revision 1 pod is still Running 1/1, so the deployment still reports Available. Fix: restore `DATABASE_URL` in the deployment spec, or roll back to revision 1.
3. **reports** (0/1, CrashLoopBackOff). The container is OOMKilled (exit 137) and has restarted twice. Its memory limit is 48Mi. Fix: raise the memory limit, and check whether the app's memory use is expected.

**Evidence**
- `kubernetes_list_deployments`: frontend 0/1 and reports 0/1, both with Available=False (MinimumReplicasUnavailable). checkout 1/1. frontend image is nginx:1.99.99-does-not-exist.
- `kubernetes_list_pods`: frontend pod waiting with ErrImagePull (image not found). checkout-7c856f898c-bjtfx is 0/1 with 2 restarts, terminated Error exit 1. reports pod is 0/1 with 2 restarts, terminated OOMKilled exit 137.
- `kubernetes_get_events`: Warnings: ErrImagePull/ImagePullBackOff for the frontend pod, and BackOff restarting the failed container for the checkout and reports pods.
- `kubernetes_pod_logs`: checkout-7c856f898c-bjtfx logs: 'FATAL: required env var DATABASE_URL is not set'.
- `kubernetes_describe_deployment`: checkout revision 1 had env DATABASE_URL. Revision 2 has no env vars and is the one progressing.
- `kubernetes_describe_pod`: reports container has a memory limit of 48Mi, last state OOMKilled exit 137, 2 restarts.

**Tool calls**
1. `kubernetes_list_pods`
2. `kubernetes_list_deployments`
3. `kubernetes_get_events`
4. `kubernetes_describe_deployment`
5. `kubernetes_pod_logs`
6. `kubernetes_describe_pod`
