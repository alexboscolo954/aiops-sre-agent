## The reports pod in demo on prod-eu is crash looping because its container is OOMKilled (exit 137). The memory limit is 48Mi, and the app loads about 200MB of rows at startup.

**Root cause** (high confidence, `resource_limits`): The reports container has a 48Mi memory limit (request 32Mi). Its log shows "building monthly report: loading 200MB of rows", so it needs several times that amount and the kernel kills it each start. The deployment is still on revision 1 with no rollout, so this is a sizing problem from the beginning, not a regression. It is not a leak, because the kill happens at startup. The limit is too small for the workload's real footprint. I did not confirm actual usage with metrics.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: 3 restarts, last terminated OOMKilled, exit code 137, ready 0/1
- `kubernetes_describe_pod`: Container app (python:3.12-alpine) has memory limit 48Mi and request 32Mi. Restart count is 3, with a BackOff warning event.
- `kubernetes_pod_logs`: Log line: "building monthly report: loading 200MB of rows", which is far above the 48Mi limit
- `kubernetes_recent_changes`: The reports deployment has only revision 1 (created). There was no rollout of it or of a dependency to blame.

**Recommendations**
1. Raise the reports memory limit and request to cover the real peak plus about 25%. Peak is at least 200MB, so start around 384Mi, and confirm with container_memory_working_set_bytes.
2. Alternatively, change the app to stream or paginate the rows instead of loading 200MB at once, so a smaller limit works.
3. Do not just restart the pod; a restart will not fix an OOM crash loop.
4. Separate issues in demo, not part of this alert: checkout crash loops after revision 2 removed the DATABASE_URL env var, and frontend has ErrImagePull on the nonexistent tag nginx:1.99.99-does-not-exist.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "prod-eu", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "prod-eu"}
4. `incidents_search` {"keywords": "reports"}
5. `kubernetes_describe_pod` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
6. `kubernetes_pod_logs` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 30}
