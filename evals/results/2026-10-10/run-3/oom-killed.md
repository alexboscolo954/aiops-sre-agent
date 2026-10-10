## The reports pod in demo is crash looping because the app container is OOMKilled (exit 137). Its 48Mi memory limit is far below the roughly 200MB the report job loads.

**Root cause** (high confidence, `oom_killed`): The container has a 48Mi memory limit (32Mi request). On startup the app logs "building monthly report: loading 200MB of rows", which exceeds the limit, so the kernel OOM-kills it on each start. There is only one revision, so this is a sizing problem from the initial deploy and not a regression.
**Severity:** high  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-7cc9978bbf-sq7r7

**Evidence**
- `kubernetes_list_pods`: reports-7cc9978bbf-sq7r7 is 0/1 ready with 2 restarts. Last terminated: OOMKilled, exit code 137.
- `kubernetes_pod_logs`: Last output before the kill: "building monthly report: loading 200MB of rows". The previous instance's logs were gone, so this is from the latest instance.
- `kubernetes_describe_pod`: Memory limit is 48Mi and request is 32Mi. There are no env vars or probes. A BackOff warning event is present.
- `kubernetes_describe_deployment`: Only revision 1 exists, created about 41s ago, with the same 48Mi limit. The deployment has 0/1 ready replicas.

**Recommended actions**
1. Raise the reports container memory limit and request. The workload needs well over 200MB, so start with a limit of about 256-512Mi and adjust to observed peak plus 25%.
2. Longer term, reduce peak memory by streaming or paginating the rows instead of loading 200MB at once.
3. Confirm usage after the change with container_memory_working_set_bytes for the pod in Prometheus.
4. Do not just restart the pod. The OOM will recur until the limit or the app's memory use changes.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_pod_logs`
4. `kubernetes_describe_pod`
5. `kubernetes_describe_deployment`
