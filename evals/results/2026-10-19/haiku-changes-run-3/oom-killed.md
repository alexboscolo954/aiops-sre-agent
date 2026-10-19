## Pod reports-55b4fffc66-hmq7f is OOMKilled (exit 137) in a loop. Its only container has a 48Mi memory limit, and the script loads about 200MB of rows, so the limit is too small for the workload. This is the reports deployment's first revision, so no earlier working revision exists to roll back to. Separately, the same namespace has a checkout rollout that removed DATABASE_URL and a frontend image tag that does not exist; neither affects this alert.

**Root cause** (medium confidence, `resource_limits`): The reports container's memory limit (48Mi, request 32Mi) is far below what its job needs. The app logs 'building monthly report: loading 200MB of rows' before the kernel kills it for exceeding the limit. The workload looks healthy but is undersized, so this is a limits problem rather than a leak or a bad rollout.
**Severity:** high  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: Running, 0/1 ready, 3 restarts, last_terminated OOMKilled exit_code 137
- `kubernetes_describe_pod`: container app (python:3.12-alpine): requests memory 32Mi, limits memory 48Mi; state and last_state both OOMKilled exit 137; events show BackOff restarting failed container app
- `kubernetes_pod_logs (previous=true)`: Last instance output: 'building monthly report: loading 200MB of rows' (previous instance logs were gone; this is the latest instance)
- `kubernetes_recent_changes`: reports revision 1 was created about 2m ago with no earlier revision, so there is no prior working version to blame; this is not a rollout regression
- `runbooks_runbook_for_alert`: KubePodCrashLooping points to the oom-killed runbook for OOMKilled exit 137; fix is to raise the limit to observed peak plus 25% or fix a leak

**Recommendations**
1. Confirm peak memory with Prometheus, e.g. max by (pod) (container_memory_working_set_bytes{namespace="demo",pod=~"reports-.*",container!=""}), since the Prometheus tool was not available in this triage.
2. Raise the reports container memory limit (and request) to observed peak plus 25%. At least 200MB of data is loaded, so the 48Mi limit is clearly insufficient. Or reduce the data loaded at once (streaming or chunking).
3. Ask the reports owners whether loading 200MB in one pass is expected, and check for a leak if memory keeps growing after the limit is raised.
4. Out of scope for this alert but in the same namespace: checkout revision 2 removed the DATABASE_URL env var from app and is crash-looping (exit 1). Roll back checkout to revision 1 or restore DATABASE_URL.
5. Out of scope but in the same namespace: frontend uses image nginx:1.99.99-does-not-exist (ErrImagePull). Fix the tag to a real image.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_recent_changes`
4. `kubernetes_describe_pod`
5. `runbooks_read_runbook`
6. `kubernetes_pod_logs`
