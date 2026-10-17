## The reports pod is crash looping because it is OOMKilled (exit 137). Its memory limit is 48Mi, but it loads about 200MB of rows at startup.

**Root cause** (high confidence, `resource_limits`): The reports container has a 48Mi memory limit (32Mi request). Its startup job logs "building monthly report: loading 200MB of rows", which is far more than the limit, so the kernel OOM-kills it on every start. This is revision 1 of the deployment, so there is no earlier working revision and it is not a rollout regression. The logs only show the 200MB figure; I did not measure actual memory usage with Prometheus.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-7cc9978bbf-sq7r7

**Evidence**
- `kubernetes_list_pods`: reports-7cc9978bbf-sq7r7: 0/1 ready, 2 restarts, last terminated OOMKilled, exit code 137
- `kubernetes_describe_pod`: The app container has a memory limit of 48Mi and a request of 32Mi. It has no probes, env vars or envFrom. Events show BackOff restarting the container.
- `kubernetes_pod_logs`: The last log line is "building monthly report: loading 200MB of rows". That is much more than the 48Mi limit. These are the latest instance's logs, since the previous instance's logs were gone.
- `kubernetes_describe_deployment`: Only revision 1 exists (python:3.12-alpine). The deployment has 0 of 1 replicas ready and is not Available.

**Recommendations**
1. Raise the reports container memory limit and request. Measure the real peak first, for example with container_memory_working_set_bytes in Prometheus. The workload holds about 200MB of rows, so start around 256-512Mi and add 25% headroom over the observed peak.
2. Longer term, change the report job to stream or paginate rows instead of loading 200MB at once, so it needs less memory.
3. Do not restart the pod. A restart does not fix an OOM crash loop.
4. After changing the limit, confirm the pod stays Running with no new restarts.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_deployment`
4. `kubernetes_pod_logs`
5. `kubernetes_describe_pod`
