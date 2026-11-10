## The reports pod (reports-55b4fffc66-hmq7f) in demo/prod-eu is crash looping because its container is OOMKilled (exit 137) repeatedly. The memory limit is 48Mi, and the app loads 200MB of rows for a monthly report. The deployment has only one revision (created 2m ago) with no recent change, so this looks like a limit that is too small for the workload rather than a bad rollout.

**Root cause** (medium confidence, `resource_limits`): The reports container has a memory limit of 48Mi (request 32Mi). Its last state is OOMKilled with exit code 137 (3 restarts). Its log line says "building monthly report: loading 200MB of rows", so the working set during load is far above 48Mi. The only revision of the deployment is the one that was created 2m ago, so nothing changed to cause this. The limit is most likely too low for the workload. Memory usage over time was not checked in Prometheus (no Prometheus tool is available), so a leak is not ruled out, but a single load of 200MB at startup already exceeds the limit.
**Severity:** high  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_describe_pod`: Container app: last_state OOMKilled exit 137, restarts 3, memory limit 48Mi, request 32Mi.
- `kubernetes_pod_logs`: Previous instance logs were gone; latest instance logged 'building monthly report: loading 200MB of rows' before being killed.
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: 0/1 ready, restarts 3, last terminated OOMKilled.
- `kubernetes_describe_deployment`: reports has one rollout revision (reports-55b4fffc66, created 2m ago), no env or image change; limits memory 48Mi.
- `kubernetes_recent_changes`: The reports deployment has only revision 1 (created). The only rollout in the window is checkout revision 2, which removed DATABASE_URL and is unrelated to reports.
- `runbooks_read_runbook`: oom-killed runbook: raise the limit to observed peak plus 25% or fix the leak; restarting only buys time.

**Recommendations**
1. Confirm peak memory: check container_memory_working_set_bytes for demo/reports in Prometheus, or measure the 200MB load locally.
2. Raise the reports memory limit (and request) to the observed peak plus 25%. At least 200MB is needed for the load, so set something around 256Mi or more, not 48Mi. Apply this as a config change through the normal deploy path.
3. If the 200MB load is larger than intended, process the rows in batches (streaming) to reduce peak memory instead of raising the limit.
4. Separately, the same namespace has other issues: checkout's DATABASE_URL was removed in revision 2 (exit 1 errors), and frontend uses a nonexistent image tag nginx:1.99.99-does-not-exist. These are outside this alert but need fixing.

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
3. `kubernetes_pod_logs` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true}
4. `kubernetes_recent_changes` {"cluster": "prod-eu"}
5. `kubernetes_describe_deployment` {"cluster": "prod-eu", "namespace": "demo", "name": "reports"}
6. `incidents_search` {"keywords": "reports OOMKilled crashloop demo"}
7. `runbooks_read_runbook` {"name": "oom-killed"}
8. `kubernetes_list_pods` {"cluster": "prod-eu", "namespace": "demo"}
9. `kubernetes_list_deployments` {"cluster": "prod-eu", "namespace": "demo"}
10. `TriageReport` {"summary": "The reports pod (reports-55b4fffc66-hmq7f) in demo/prod-eu is crash looping because its container is OOMKilled (exit 137) repeatedly. The memory limit is 48Mi, and the app loads 200MB of rows for a monthly report. The deployment has only one revision (created 2m ago) with no recent chan
