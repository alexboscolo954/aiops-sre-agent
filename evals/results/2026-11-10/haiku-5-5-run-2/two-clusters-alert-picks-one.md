## Pod reports-55b4fffc66-hmq7f (demo, prod-eu) is crash looping with OOMKilled (exit 137). The container's memory limit is 48Mi, while the app starts by loading 200MB of rows for a monthly report. The reports deployment has one revision (created ~2m ago), so this looks like a limit that is too small for the workload rather than a bad rollout.

**Root cause** (medium confidence, `resource_limits`): The container 'app' has a memory limit of 48Mi (request 32Mi). It is OOMKilled on each start (last_state OOMKilled, exit 137, restarts 3). Its only log line is "building monthly report: loading 200MB of rows", so the job needs far more than 48Mi just to load its data. The limit is too small for the workload. The only revision of reports (revision 1) is the one crashing, so no rollout regression is involved. Confidence is medium: I did not get Prometheus memory usage, and the previous-instance logs were gone, so the 200MB figure is the only sizing evidence.
**Severity:** high  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f container app: limits memory 48Mi, requests memory 32Mi; last_state OOMKilled exit 137; restarts 3
- `kubernetes_pod_logs`: Previous logs gone; latest instance logged 'building monthly report: loading 200MB of rows' before being killed
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: Running, 0/1 ready, restarts 3, last_terminated OOMKilled
- `kubernetes_describe_deployment`: reports has a single rollout_history revision (1, created 2m ago), image python:3.12-alpine, no env changes; Available=False MinimumReplicasUnavailable
- `kubernetes_recent_changes`: The only reports change is revision 1 'created'. Other recent rollouts are in checkout (env DATABASE_URL removed, revision 2) and frontend (image nginx:1.99.99-does-not-exist), which are not related to reports

**Recommendations**
1. Confirm the real memory peak in Prometheus over the last hours, if metrics are available.
2. Raise the reports container memory limit and request to the observed peak plus about 25%. Loading 200MB of rows suggests well above 48Mi. This change needs human approval.
3. Alternatively, stream the rows in the job instead of loading all 200MB at once (code-side fix).
4. Separately: checkout revision 2 removed DATABASE_URL and is crashing with exit 1 (restore the env var or roll back). frontend uses a nonexistent image tag nginx:1.99.99-does-not-exist (fix the tag).

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
3. `kubernetes_pod_logs` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true}
4. `kubernetes_recent_changes` {"cluster": "prod-eu"}
5. `kubernetes_describe_deployment` {"cluster": "prod-eu", "namespace": "demo", "name": "reports"}
6. `incidents_search` {"keywords": "reports OOMKilled crashloop demo"}
7. `kubernetes_list_pods` {"cluster": "prod-eu", "namespace": "demo", "label_selector": "app=reports"}
8. `runbooks_read_runbook` {"name": "oom-killed"}
9. `TriageReport` {"summary": "Pod reports-55b4fffc66-hmq7f (demo, prod-eu) is crash looping with OOMKilled (exit 137). The container's memory limit is 48Mi, while the app starts by loading 200MB of rows for a monthly report. The reports deployment has one revision (created ~2m ago), so this looks like a limit that i
10. `TriageReport` {"summary": "Pod reports-55b4fffc66-hmq7f (demo, prod-eu) is crash looping with OOMKilled (exit 137). The container's memory limit is 48Mi, while the app starts by loading 200MB of rows for a monthly report. The reports deployment has one revision (created ~2m ago), so this looks like a limit that i
