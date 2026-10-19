## The reports pod is crash looping because its container is OOMKilled (exit 137) under a 48Mi memory limit. Its startup log shows it loading 200MB of rows, so the limit is far too small for the workload. This is a resource-limit problem, not a bad rollout: reports has only revision 1, created 2m ago, and has never run successfully.

**Root cause** (high confidence, `resource_limits`): The reports container has a memory limit of 48Mi, but the job loads about 200MB of rows at startup. The kernel OOM-kills it each time, and Kubernetes backs off restarts. The deployment was created with this limit and has no earlier revision that worked.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f is Running 0/1 with 3 restarts; last_terminated app = OOMKilled, exit code 137.
- `kubernetes_describe_pod`: Container app (image python:3.12-alpine) has limits.memory 48Mi and requests.memory 32Mi; state and last_state both OOMKilled, exit 137, restarts 3.
- `kubernetes_pod_logs (previous=true)`: Last log line before the kill: 'building monthly report: loading 200MB of rows'. The previous instance's logs were gone, so this is the latest instance's output.
- `kubernetes_describe_deployment`: reports has a single rollout revision (1, created 2m ago) with the same 48Mi limit; Available=False, MinimumReplicasUnavailable.
- `kubernetes_recent_changes`: The only recent rollout in the cluster is checkout revision 2 (DATABASE_URL removed). It is unrelated to reports, which has no revision change.
- `runbooks_runbook_for_alert`: KubePodCrashLooping runbook: OOMKilled points to the oom-killed runbook. Fix is to raise the limit to observed peak plus 25% or fix the leak.

**Recommendations**
1. Raise reports' memory limit (and request) well above the roughly 200MB the job loads, e.g. 256Mi or more, after checking real peak usage. Apply it via a reviewed change to the reports deployment, not a bare restart, since a restart will not fix the kill.
2. Alternatively, change the job to stream rows instead of loading all 200MB at once, which keeps the 48Mi limit workable.
3. Confirm the new peak with container_memory_working_set_bytes for demo/reports once it runs.
4. Separately, checkout (not in this alert group) is also crash looping: revision 2 removed the DATABASE_URL env var, which is a bad_config rollout. Roll checkout back to revision 1 or restore DATABASE_URL and triage it under its own alert.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_pod`
4. `kubernetes_describe_deployment`
5. `kubernetes_recent_changes`
6. `kubernetes_pod_logs`
