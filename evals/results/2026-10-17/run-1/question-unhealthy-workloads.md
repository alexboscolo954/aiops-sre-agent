Three workloads in `demo` are unhealthy. Each has a different cause.

**1. frontend: image can't be pulled (ErrImagePull / ImagePullBackOff)**
- The deployment is 0/1 and its pod is Pending.
- It uses the image `nginx:1.99.99-does-not-exist`, and the registry returns "not found" for that tag.
- Fix: point the deployment at a real nginx tag.

**2. checkout: crash loop after a bad rollout (partially degraded)**
- Revision 2 (ReplicaSet `checkout-7c856f898c`) crash-loops. Its pod is 0/1 with 2 restarts and exit code 1.
- The logs say `FATAL: required env var DATABASE_URL is not set`.
- Revision 1 (`checkout-7784c7f885`) had the `DATABASE_URL` env var. Revision 2 has no env vars at all, so it was dropped in the rollout.
- The old revision-1 pod is still running 1/1, so the deployment still reports Available. The rollout can't complete while the new pod crashes.
- Fix: roll back to revision 1, or restore `DATABASE_URL` in the deployment. A restart won't help.

**3. reports: OOMKilled**
- The deployment is 0/1, and its pod is crash-looping with 2 restarts. The last termination was `OOMKilled` (exit 137).
- The memory limit is 48Mi. The app logs `building monthly report: loading 200MB of rows`, so it needs far more memory than the limit allows.
- Fix: raise the memory limit and request. The runbook suggests observed peak plus 25%. Alternatively, change the job to stream or paginate the rows instead of loading them all at once.

**Evidence**
- `kubernetes_list_pods`: frontend-79765fc9d-pqg7h is Pending with ErrImagePull: docker.io/library/nginx:1.99.99-does-not-exist not found
- `kubernetes_get_events`: Warning events for frontend: Failed to pull image, ErrImagePull, ImagePullBackOff. BackOff events for the checkout and reports pods.
- `kubernetes_list_deployments`: frontend 0/1 and reports 0/1, both with Available=False (MinimumReplicasUnavailable). checkout is 1/1.
- `kubernetes_pod_logs`: checkout-7c856f898c-bjtfx (current and previous run): 'FATAL: required env var DATABASE_URL is not set'
- `kubernetes_describe_deployment`: checkout revision 1 has env DATABASE_URL. Revision 2 (checkout-7c856f898c) has no env. The Progressing condition is ReplicaSetUpdated.
- `kubernetes_describe_pod`: reports pod: memory limit 48Mi, last state OOMKilled with exit code 137, 2 restarts
- `kubernetes_pod_logs`: reports pod logs: 'building monthly report: loading 200MB of rows'

**Tool calls**
1. `kubernetes_list_pods`
2. `kubernetes_list_deployments`
3. `kubernetes_get_events`
4. `kubernetes_pod_logs`
5. `kubernetes_describe_deployment`
6. `kubernetes_describe_pod`
7. `kubernetes_pod_logs`
8. `kubernetes_list_pods`
9. `kubernetes_describe_deployment`
10. `kubernetes_describe_deployment`
11. `runbooks_search_runbooks`
12. `runbooks_read_runbook`
13. `kubernetes_list_pods`
14. `kubernetes_describe_pod`
15. `runbooks_read_runbook`
16. `kubernetes_pod_logs`
17. `runbooks_read_runbook`
18. `kubernetes_list_pods`
19. `kubernetes_pod_logs`
20. `kubernetes_get_events`
