Three of the three workloads in `demo` are unhealthy. Each has a different cause:

1. **frontend**: 0/1 ready. The pod is stuck in `ErrImagePull`/`ImagePullBackOff`. The deployment points at the image `nginx:1.99.99-does-not-exist`, and that tag doesn't exist on Docker Hub. **Fix:** set the image to a valid nginx tag.

2. **reports**: 0/1 ready, crash looping with 2 restarts. The container is `OOMKilled` (exit 137). Its memory limit is only 48Mi, and the app logs `building monthly report: loading 200MB of rows`, so it needs far more than the limit allows. **Fix:** raise the memory limit and request, or change the app to stream or batch the rows. The runbook suggests observed peak plus 25%. The limit would need to be well above 200MB for this workload.

3. **checkout**: degraded after a bad rollout. Revision 2 (`checkout-7c856f898c`) crash loops with exit code 1. Its log says `FATAL: required env var DATABASE_URL is not set`. Revision 1 had a `DATABASE_URL` env var and revision 2 doesn't. The old pod from revision 1 (`checkout-7784c7f885-pwjtr`) is still running 1/1, so the deployment shows as available for now. **Fix:** restore `DATABASE_URL` in the deployment spec, or roll back to revision 1.

**Evidence**
- `kubernetes_list_pods`: frontend pod is Pending with ErrImagePull: docker.io/library/nginx:1.99.99-does-not-exist not found
- `kubernetes_list_deployments`: frontend 0/1 and reports 0/1 with Available=False (MinimumReplicasUnavailable); checkout shows 1/1 only because the old pod is still serving
- `kubernetes_describe_pod`: reports container limit is 48Mi, last state OOMKilled exit 137, 2 restarts
- `kubernetes_pod_logs`: reports log: 'building monthly report: loading 200MB of rows'
- `kubernetes_pod_logs`: checkout-7c856f898c-bjtfx log: 'FATAL: required env var DATABASE_URL is not set'; the pod exited with code 1 (Error)
- `kubernetes_describe_deployment`: checkout revision 1 has env DATABASE_URL; revision 2 (checkout-7c856f898c) has env []
- `kubernetes_get_events`: BackOff warnings for the checkout and reports pods; ImagePullBackOff and ErrImagePull warnings for the frontend pod
- `runbooks_read_runbook`: The oom-killed runbook says to raise the limit to observed peak plus 25%, or fix the leak

**Tool calls**
1. `kubernetes_list_pods`
2. `kubernetes_list_deployments`
3. `kubernetes_get_events`
4. `kubernetes_pod_logs`
5. `kubernetes_describe_deployment`
6. `kubernetes_describe_pod`
7. `kubernetes_pod_logs`
8. `runbooks_search_runbooks`
9. `runbooks_read_runbook`
10. `kubernetes_describe_deployment`
11. `kubernetes_describe_deployment`
12. `runbooks_read_runbook`
13. `kubernetes_list_pods`
