## The reports pod is crash looping because its container is OOMKilled (exit 137) under a 48Mi memory limit. The job logs say it is loading 200MB of rows, which is far above that limit. This is a single-revision deployment, so no recent rollout is involved.

**Root cause** (medium confidence, `resource_limits`): The memory limit (48Mi, request 32Mi) is far too small for the workload, which loads about 200MB of rows for its monthly report. The kernel kills the container on each run, and Kubernetes backs off restarts. A leak is not ruled out, but the log line alone accounts for more memory than the limit allows.
**Severity:** high  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-7cc9978bbf-sq7r7

**Evidence**
- `kubernetes_describe_pod`: Container 'app' (python:3.12-alpine) state terminated reason OOMKilled, exit_code 137, restarts 2; limits memory 48Mi, requests memory 32Mi.
- `kubernetes_describe_pod`: Events show repeated Started/Created and 'Back-off restarting failed container app'; Ready=False ContainersNotReady.
- `kubernetes_pod_logs (previous=true)`: Previous instance logs are gone; latest instance shows 'building monthly report: loading 200MB of rows' before the kill.
- `kubernetes_describe_deployment`: Only one revision (revision 1, python:3.12-alpine, no env changes); Available=False MinimumReplicasUnavailable. No recent rollout.
- `runbooks_runbook_for_alert`: KubePodCrashLooping runbook: OOMKilled points to the oom-killed runbook; a restart does not fix a crash loop.

**Recommendations**
1. Raise the memory limit and request for the reports container well above 48Mi, sized to observed peak plus about 25%. The 200MB data load alone suggests something like 256Mi or more; confirm with metrics.
2. Check memory usage in Prometheus with max by (pod) (container_memory_working_set_bytes{namespace="demo",container="app"}) to tell a flat limit-too-small pattern from steady growth (a leak).
3. If usage grows steadily across runs, investigate the report job for a leak, such as loading all rows into memory at once; stream or chunk the rows instead.
4. Do not restart the pod as a fix; it will crash again on the next run.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_describe_pod`
3. `kubernetes_pod_logs`
4. `kubernetes_describe_deployment`
