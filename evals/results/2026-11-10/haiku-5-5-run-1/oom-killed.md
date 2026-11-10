## Pod reports-55b4fffc66-hmq7f (demo) is crash looping with OOMKilled (exit 137) and 3 restarts. The container memory limit is 48Mi, and the workload is a Python script that is loading 200MB of rows into memory for a monthly report. The limit is far below the working set, so the kernel kills it on each start. This is a resource-limit problem, not a rollout regression: reports has only revision 1, created 2m ago.

**Root cause** (medium confidence, `resource_limits`): The reports container has memory limit 48Mi (request 32Mi). Its last log line is "building monthly report: loading 200MB of rows", so its working set is at least 200MB, several times the limit. The kernel OOM-kills it (exit 137, last_state OOMKilled, 3 restarts). The deployment has only revision 1, so no recent change caused this. The limit was set too low for the workload from the start. Prometheus was not queried, so the peak usage is inferred from the log message, not measured.
**Severity:** high  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_describe_pod`: Container app: limits memory 48Mi, requests 32Mi; state and last_state OOMKilled, exit_code 137, restarts 3.
- `kubernetes_pod_logs`: Latest instance log (previous instance gone): 'building monthly report: loading 200MB of rows'.
- `kubernetes_describe_deployment`: reports has a single rollout revision (1, created 2m ago) with memory limit 48Mi; no config changes.
- `kubernetes_recent_changes`: Only change for reports is revision 1 'created'. The recent rollout is checkout revision 2, which removed DATABASE_URL and is unrelated to reports.
- `runbooks_runbook_for_alert`: KubePodCrashLooping runbook: OOMKilled (exit 137) points to the oom-killed runbook.

**Recommendations**
1. Confirm peak memory with Prometheus: max by (pod) (container_memory_working_set_bytes{namespace="demo", pod=~"reports.*"}) over the last hours. It was not checked in this triage.
2. Raise the reports container memory limit (and request) to the observed peak plus 25%, or, if it must stay small, change the script to stream rows instead of loading 200MB at once. The 48Mi limit cannot fit 200MB of rows.
3. Roll out the change and check that the pod reaches Ready with 0 OOMKilled restarts.
4. Separate issue, not the cause of this alert: checkout revision 2 removed DATABASE_URL and its pod is in Error (exit 1), and frontend uses a nonexistent image tag (nginx:1.99.99-does-not-exist, ErrImagePull). Triage them separately.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true}
4. `kubernetes_recent_changes` {"cluster": "kind"}
5. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
6. `incidents_search` {"keywords": "reports OOMKilled crashloop"}
7. `runbooks_read_runbook` {"name": "oom-killed"}
8. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
9. `TriageReport` {"summary": "Pod reports-55b4fffc66-hmq7f (demo) is crash looping with OOMKilled (exit 137) and 3 restarts. The container memory limit is 48Mi, and the workload is a Python script that is loading 200MB of rows into memory for a monthly report. The limit is far below the working set, so the kernel ki
10. `TriageReport` {"summary": "Pod reports-55b4fffc66-hmq7f (demo) is crash looping with OOMKilled (exit 137) and 3 restarts. The container memory limit is 48Mi, and the workload is a Python script that is loading 200MB of rows into memory for a monthly report. The limit is far below the working set, so the kernel ki
