## The reports pod in demo is crash looping because it is OOMKilled (exit 137). Its memory limit is 48Mi, but the job loads about 200MB of rows at startup.

**Root cause** (high confidence, `resource_limits`): The reports container has a 48Mi memory limit (32Mi request). On startup it builds the monthly report by loading ~200MB of rows, which exceeds the limit, so the kernel OOM-kills it on every start. There is only one revision, so this is not a rollout regression. The limit is too low for this workload.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-7cc9978bbf-sq7r7

**Evidence**
- `kubernetes_list_pods`: reports-7cc9978bbf-sq7r7: restarts=2, last terminated OOMKilled, exit code 137, ready 0/1
- `kubernetes_describe_pod`: Container app has limits.memory=48Mi, requests.memory=32Mi; BackOff warning on restarting the container
- `kubernetes_pod_logs`: Log line: 'building monthly report: loading 200MB of rows', which is far above the 48Mi limit (the previous instance's logs were gone, so this is from the latest instance)
- `kubernetes_describe_deployment`: Only revision 1 exists (created ~41s ago), with the same 48Mi limit, so there is no earlier working revision to roll back to

**Recommendations**
1. Raise the reports memory limit and request. Observed need is at least ~200MB, so try a limit of about 256-384Mi (peak plus 25%) and a request of about 256Mi.
2. Better still, change the report job to stream or paginate rows instead of loading 200MB at once, so it fits in a smaller footprint.
3. After the change, confirm with kubernetes_list_pods that the pod stays Running with no new OOMKilled restarts. Check container_memory_working_set_bytes in Prometheus to size the limit.
4. Do not just restart the pod. It will be OOM-killed again.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_pod`
4. `kubernetes_pod_logs`
5. `kubernetes_describe_deployment`
