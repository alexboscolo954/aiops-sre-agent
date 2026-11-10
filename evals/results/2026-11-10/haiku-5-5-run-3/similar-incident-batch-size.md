## Pod reports-55b4fffc66-hmq7f is crash looping because its app container is OOMKilled (exit 137) at a 48Mi memory limit. The deployment has no env vars, and the log shows it loading 200MB of rows at once. A past Report on this same workload found the cause to be an unset REPORTS_BATCH_SIZE, but that was not verified here.

**Root cause** (medium confidence, `bad_config`): The reports container is OOMKilled at its 48Mi limit (last state OOMKilled, exit 137, restarts 3). Its log shows "building monthly report: loading 200MB of rows", so the job loads the whole dataset into memory. The deployment's env is empty, so REPORTS_BATCH_SIZE is not set. Per the past Report (OPS-112), an unset batch size makes the job load every row. This is a lead from a past conclusion, and I did not confirm it in the current env or code. The 48Mi limit is far below what loading 200MB needs, so raising the limit alone would only delay the next kill. The rollout history has only revision 1, so this is not a new-revision regression.
**Severity:** high  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_describe_pod`: container app: state and last_state terminated OOMKilled, exit_code 137, restarts 3; limits memory 48Mi, requests memory 32Mi
- `kubernetes_pod_logs`: previous instance logs gone; latest instance shows 'building monthly report: loading 200MB of rows'
- `kubernetes_describe_deployment`: reports deployment has a single revision (1, created 2m ago); container env [] and env_from []; Available=False, MinimumReplicasUnavailable
- `kubernetes_recent_changes`: no reports rollout in the window; only the reports revision 1 creation. The checkout DATABASE_URL removal is a separate workload and not related to this alert
- `incidents_search`: past Report 5b0e2c4e (OPS-112) matched: reports OOMKilled at 48Mi because REPORTS_BATCH_SIZE is unset, so the job loads all rows; suggested REPORTS_BATCH_SIZE=1000
- `runbooks_read_runbook`: oom-killed runbook: raise the limit to observed peak plus 25% or fix the leak; restarting only buys time

**Recommendations**
1. Confirm the batch-size config: check the reports source or team manifests for how REPORTS_BATCH_SIZE is read. Then set REPORTS_BATCH_SIZE=1000 on deploy/reports in the team's manifests (this is the suggestion from the past Report, not yet verified here).
2. Do not only raise the 48Mi memory limit. The job loads ~200MB of rows, so a bigger limit just delays the next kill. Use a streamed or batched load.
3. After the change, confirm the pod stays Running with no OOMKilled restarts, and check container_memory_working_set_bytes for demo/reports stays well under the limit.
4. Do not restart the pod as a fix; a restart does not fix a crash loop.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
5. `incidents_search` {"keywords": "reports OOMKilled crashloop"}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 50}
7. `incidents_read` {"id": "5b0e2c4e-9a51-4d1e-8f3a-2f6c7d1e0a93"}
8. `runbooks_read_runbook` {"name": "oom-killed"}
9. `TriageReport` {"summary": "Pod reports-55b4fffc66-hmq7f is crash looping because its app container is OOMKilled (exit 137) at a 48Mi memory limit. The deployment has no env vars, and the log shows it loading 200MB of rows at once. A past Report on this same workload found the cause to be an unset REPORTS_BATCH_SI
