## In prod-eu, the reports pod demo/reports-55b4fffc66-hmq7f is crash looping because it keeps getting OOMKilled (exit 137, 3 restarts). The container's memory limit is 48Mi, but it logs that it is loading 200MB of rows for the monthly report.

**Root cause** (high confidence, `resource_limits`): The 'app' container (python:3.12-alpine) has a 48Mi memory limit and a 32Mi request. On startup it logs 'building monthly report: loading 200MB of rows', so it needs more than 200Mi plus Python overhead. The kernel kills it at the limit every time: OOMKilled, exit code 137, on both the current and previous runs. The deployment is still on revision 1, created about 2 minutes ago. No rollout changed reports, so a rollback won't help. The limit was too small from the start. No memory metrics were available, so the 'needs over 200Mi' figure comes from the app's own log line, not a measured peak.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: Running, 0/1 ready, 3 restarts. Current and last termination are both OOMKilled, exit code 137.
- `kubernetes_describe_pod`: Container 'app' image python:3.12-alpine: requests cpu 10m, memory 32Mi; limit memory 48Mi. Warning BackOff restarting the failed container.
- `kubernetes_pod_logs`: Latest run logs 'building monthly report: loading 200MB of rows' (the previous run's logs are gone), about 4x the 48Mi limit.
- `kubernetes_recent_changes`: reports has only revision 1, created 2m ago, so no rollout to blame. The only rollout was checkout revision 2 (DATABASE_URL removed), which is unrelated to reports.

**Recommendations**
1. Raise the memory on Deployment demo/reports to fit the 200MB dataset with headroom. For example, set the limit to about 320Mi and the request to about 256Mi, then tune it to the observed peak plus 25% as the oom-killed runbook says.
2. After the change, watch the new pod: it should get past 'loading 200MB of rows' without restarting, and its last_terminated should no longer show OOMKilled.
3. Longer term, have the report job stream or batch its rows instead of loading the whole 200MB dataset into memory, so memory use doesn't keep growing with the data.
4. Don't just restart the pod: it will be OOMKilled again at the same 48Mi limit.
5. Separately, two other workloads in demo are broken, unrelated to this alert: checkout is crash looping after revision 2 removed DATABASE_URL, and frontend can't pull image nginx:1.99.99-does-not-exist. Triage them on their own alerts.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "prod-eu", "namespace": "demo"}
3. `kubernetes_describe_pod` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
4. `kubernetes_pod_logs` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true}
5. `kubernetes_recent_changes` {"cluster": "prod-eu"}
6. `incidents_search` {"keywords": "reports crashloop"}
