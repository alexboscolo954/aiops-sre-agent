## The reports pod in demo is crash looping because its container is OOMKilled (exit 137). The memory limit is 48Mi, and the app tries to load about 200MB of rows at startup.

**Root cause** (high confidence, `oom_killed`): The `app` container has a 48Mi memory limit (32Mi request). On startup it builds the monthly report and loads about 200MB of rows, which far exceeds the limit, so the kernel OOM-kills it on every start. The deployment has only one revision, so this is a sizing problem from the start and not a regression.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-7cc9978bbf-ddp5d

**Evidence**
- `kubernetes_list_pods`: reports-7cc9978bbf-ddp5d: 0/1 ready, 2 restarts, last_terminated OOMKilled, exit code 137
- `kubernetes_pod_logs`: Log line: 'building monthly report: loading 200MB of rows'. This is the latest instance's log, because the previous instance's logs were gone.
- `kubernetes_describe_pod`: Memory limit 48Mi, request 32Mi. Back-off restarting failed container app (BackOff warning).
- `kubernetes_describe_deployment`: Only revision 1 exists (python:3.12-alpine). 0/1 replicas are available (MinimumReplicasUnavailable).

**Recommended actions**
1. Raise the memory limit on the reports deployment to well above the 200MB working set. Peak plus 25% is a reasonable rule, and a limit of about 384Mi with a matching request is a sensible starting point. Confirm the real peak with container_memory_working_set_bytes.
2. Alternatively, change the report job to stream or paginate rows instead of loading 200MB at once, so it fits in a small limit.
3. After the change, check that the pod becomes Ready and stops restarting.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_pod_logs`
4. `kubernetes_describe_pod`
5. `kubernetes_describe_deployment`
