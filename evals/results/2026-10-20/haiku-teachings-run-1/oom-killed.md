## The reports pod is crash looping because its container is OOMKilled (exit 137) at a 48Mi memory limit while it loads about 200MB of rows for the monthly report. The only revision of the reports deployment is the one that is failing, so this is a limit that is too low, not a rollout regression.

**Root cause** (high confidence, `resource_limits`): The reports deployment (single revision 1, python:3.12-alpine) sets memory limit 48Mi and request 32Mi. The app logs 'building monthly report: loading 200MB of rows' before dying. Both the current and last container states are OOMKilled with exit code 137, and the restart count is 3. The limit is far below the roughly 200MB working set the job needs, so the kernel kills it on every run. The checkout rollout (revision 2, DATABASE_URL removed) happened in a different workload and shows no link to reports.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_describe_pod`: Container app: limits memory 48Mi, requests memory 32Mi; state and last_state both terminated OOMKilled, exit_code 137; restarts 3; Ready False (ContainersNotReady).
- `kubernetes_pod_logs`: Previous-instance logs unavailable; latest instance shows 'building monthly report: loading 200MB of rows' as the last line before the kill.
- `kubernetes_describe_deployment`: reports has one revision (revision 1, created 2m ago, unchanged image python:3.12-alpine, no env). Deployment Available False: MinimumReplicasUnavailable, ready 0 of 1 desired.
- `kubernetes_recent_changes`: The only recent rollout is checkout revision 2 (env DATABASE_URL removed). No reports rollout in the window, so the reports failure is not a rollout regression.
- `incidents_search`: No past Report in the last 90 days matches reports/OOMKilled, so there is no prior fix to compare against.

**Recommendations**
1. Raise the reports container memory limit well above the observed ~200MB working set, for example to 256Mi or 384Mi, and raise the request to match. Then confirm the pod reaches Ready and stops restarting. This needs a change to the deployment spec, so it goes through the usual approval path.
2. If the 48Mi limit was set on purpose, switch the job to stream rows instead of loading all 200MB into memory, so it fits a small limit.
3. Check Prometheus container_memory_working_set_bytes for demo/reports over a full run to confirm the real peak before picking the final limit. Prometheus was not queried in this triage.
4. Separately, look into checkout revision 2, which removed DATABASE_URL from its app container. That is unrelated to this alert but is likely to break checkout at startup.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "container": "app", "tail_lines": 50, "previous": true}
5. `incidents_search` {"keywords": "reports demo OOMKilled", "days": 90, "limit": 5}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
