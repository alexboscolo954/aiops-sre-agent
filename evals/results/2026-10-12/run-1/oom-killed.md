## The reports pod in demo is crash looping because it is OOMKilled (exit 137). Its memory limit is 48Mi, and the job loads about 200MB of rows.

**Root cause** (high confidence, `resource_limits`): The reports container has a 48Mi memory limit (32Mi request). On startup it logs 'building monthly report: loading 200MB of rows', so the workload needs far more memory than the limit allows. The kernel OOM-kills it on each start. This is revision 1 of the deployment, so there is no earlier working revision and it is not a rollout regression.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-7cc9978bbf-sq7r7

**Evidence**
- `kubernetes_list_pods`: reports-7cc9978bbf-sq7r7 has restarts=2 and last_terminated OOMKilled, exit code 137, with ready 0/1
- `kubernetes_describe_pod`: The app container has limits.memory=48Mi and requests.memory=32Mi. There are no probes. Events show BackOff restarting the failed container.
- `kubernetes_pod_logs`: The last log line is 'building monthly report: loading 200MB of rows'. This is far more than the 48Mi limit. The previous instance's logs were gone, so this is from the latest instance.
- `kubernetes_describe_deployment`: Only revision 1 exists (reports-7cc9978bbf), so there is no earlier working revision to roll back to.

**Recommended actions**
1. Raise the memory limit and request on the reports deployment. The workload loads about 200MB, so start with a limit of roughly 384Mi and adjust to measured peak plus 25%.
2. Check actual peak memory with Prometheus (container_memory_working_set_bytes for the pod) to size the limit.
3. Consider changing the report job to stream or paginate rows instead of loading 200MB at once, if the memory cost is a concern.
4. Do not restart the pod. A restart does not fix an OOM crash loop.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_pod_logs`
4. `kubernetes_describe_deployment`
5. `kubernetes_describe_pod`
