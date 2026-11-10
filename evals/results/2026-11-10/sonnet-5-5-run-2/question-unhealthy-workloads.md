All three deployments in `demo` are unhealthy. Each shows 0/1 ready and `Available=False` with reason `MinimumReplicasUnavailable`. Each has a different cause.

1. **checkout** is crash-looping (3 restarts, exit code 1). The log says `FATAL: required env var DATABASE_URL is not set`. Revision 2 rolled out about 48s ago and removed the `DATABASE_URL` env var from the `app` container, which is the likely trigger. To fix it, restore `DATABASE_URL` in the deployment or roll back to revision 1.

2. **frontend** can't start because of `ErrImagePull` / `ImagePullBackOff`. The image `nginx:1.99.99-does-not-exist` doesn't exist (`not found` from docker.io). It has been on that image since its first revision, so there is no earlier working revision to roll back to. To fix it, set a valid nginx tag.

3. **reports** is being `OOMKilled` (exit 137, 3 restarts, back-off). The memory limit is 48Mi and the container's last log line is `building monthly report: loading 200MB of rows`, so it loads far more data than the limit allows. To fix it, raise the memory limit well above ~200Mi, or have the job load the rows in batches.

All three pods also had a one-off `FailedScheduling` event (untolerated node taint) when they were created about 2 minutes ago. They were scheduled afterwards, so it is not the current cause.

No past incidents matched these workloads.

**Evidence**
- `kubernetes_list_pods`: checkout 0/1 with 3 restarts, terminated Error exit 1; frontend Pending with ErrImagePull for nginx:1.99.99-does-not-exist (not found); reports 0/1 with 3 restarts, terminated OOMKilled exit 137
- `kubernetes_list_deployments`: checkout, frontend and reports all 0/1 ready with Available=False, MinimumReplicasUnavailable
- `kubernetes_pod_logs`: checkout log: 'FATAL: required env var DATABASE_URL is not set'. The reports log was checked in a separate call and shows 'building monthly report: loading 200MB of rows'.
- `kubernetes_recent_changes`: checkout revision 2 rolled out 48s ago with env_removed: app: [DATABASE_URL]
- `kubernetes_describe_pod`: reports container app has memory limit 48Mi (request 32Mi), last state OOMKilled exit 137, BackOff events, 3 restarts
- `kubernetes_describe_deployment`: frontend has only revision 1, with image nginx:1.99.99-does-not-exist; Available=False
- `kubernetes_get_events`: Warning events: BackOff for checkout and reports, ErrImagePull/ImagePullBackOff for frontend, and FailedScheduling (untolerated taint) for all three about 2m ago

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 30}
4. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "tail_lines": 20}
6. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
7. `incidents_search` {"keywords": "checkout frontend reports demo"}
8. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 5, "previous": true}
9. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "frontend"}
10. `read_more` {"result_id": "none"}
11. `runbooks_search_runbooks` {"keywords": "oom crashloop imagepull"}
12. `kubernetes_get_events` {"cluster": "kind", "namespace": "demo"}
