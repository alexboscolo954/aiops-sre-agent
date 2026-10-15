## The reports pod in demo is crash looping because it is OOMKilled (exit 137). The 48Mi memory limit is below what the report job needs: it loads about 200MB of rows at startup.

**Root cause** (high confidence, `resource_limits`): The container's memory limit is 48Mi (request 32Mi). The app logs 'building monthly report: loading 200MB of rows', so its working set is well above the limit and the kernel OOM-kills it on each start. Reports has only one revision, so this is not a rollout regression. Whether the 200MB load is intended or an app problem (it could be streamed or paginated) was not established.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-7cc9978bbf-sq7r7

**Evidence**
- `kubernetes_list_pods`: reports-7cc9978bbf-sq7r7 has 2 restarts, last terminated reason OOMKilled, exit code 137, and is 0/1 ready.
- `kubernetes_describe_deployment`: Container app has a memory limit of 48Mi and a request of 32Mi. There is only one revision (revision 1), so there was no earlier working version.
- `kubernetes_pod_logs`: The log reads 'building monthly report: loading 200MB of rows', which is far above the 48Mi limit. The previous instance's logs were gone, so this came from the latest instance.
- `kubernetes_describe_pod`: Container state is OOMKilled with exit 137. There are BackOff warning events and no liveness or readiness probes.

**Recommendations**
1. Raise the memory limit and request for the reports container. Peak usage is at least 200MB, so start with a limit of about 512Mi and confirm with container_memory_working_set_bytes.
2. If the 200MB load is not intended, change the app to stream or paginate the rows so that it fits within a smaller limit.
3. Do not restart the pod. A restart will not fix an OOM crash loop.
4. Separately, the checkout and frontend pods in the same namespace are also unhealthy. Checkout has a pod in Error and frontend is in ErrImagePull because tag nginx:1.99.99-does-not-exist is not found. They are not part of this alert.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_deployment`
4. `kubernetes_pod_logs`
5. `kubernetes_describe_pod`
