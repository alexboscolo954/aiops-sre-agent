## The reports pod is crash looping because its app container is OOMKilled (exit 137) at a 48Mi memory limit while it loads about 200MB of rows for the monthly report. This is a resource limit problem, not a rollout: reports has only its first revision, created about 2 minutes before the alert.

**Root cause** (medium confidence, `resource_limits`): The app container has a memory limit of 48Mi (request 32Mi). Its last state and current state are both OOMKilled with exit code 137, and restarts is 3. The previous instance's log ends at "building monthly report: loading 200MB of rows", so the job tries to hold roughly 200MB in memory, about four times the limit. The limit is too small for a healthy workload. No recent change explains it: reports is at revision 1, created 2 minutes ago, with no diff to compare. The checkout rollout (revision 2, DATABASE_URL removed) is unrelated to this pod's OOM.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_describe_pod`: Container app (python:3.12-alpine) has limits memory 48Mi and requests memory 32Mi; state and last_state are terminated OOMKilled, exit_code 137, restarts 3; Ready=False ContainersNotReady.
- `kubernetes_pod_logs`: Previous-instance logs are gone; the latest instance shows only "building monthly report: loading 200MB of rows".
- `kubernetes_recent_changes`: reports revision 1 was created 2m ago with an empty diff, so there is no rollout to blame. checkout revision 2 (DATABASE_URL removed) is a separate workload and not related to this pod's OOM.
- `runbooks_runbook_for_alert`: KubePodCrashLooping points to the pod-crashlooping runbook, which says OOMKilled (exit 137) goes to the oom-killed runbook: compare the limit with real usage; a limit far below the working set means the limit is too small.

**Recommendations**
1. Raise the reports container memory limit well above the observed peak (roughly 200MB of loaded rows plus overhead, so about 256Mi or more), and raise the request to match. Apply it through the deployment's manifest or Helm values, not by hand.
2. Alternatively, reduce the job's memory footprint by streaming or chunking the 200MB row load instead of loading it all at once, if that is feasible.
3. Confirm the peak with Prometheus, for example max by (pod) (container_memory_working_set_bytes{namespace="demo",pod=~"reports-.*"}), which was not available in this investigation.
4. Do not restart the pod to fix this; a restart only resets the back-off and the next run gets OOMKilled again.

Runbook: `oom-killed`

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
2. `kubernetes_pod_logs` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "container": null, "tail_lines": 100, "previous": true}
3. `kubernetes_recent_changes` {"cluster": "prod-eu", "since_minutes": 360}
4. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
5. `incidents_search` {"keywords": "reports OOMKilled demo", "days": 90, "limit": 5}
