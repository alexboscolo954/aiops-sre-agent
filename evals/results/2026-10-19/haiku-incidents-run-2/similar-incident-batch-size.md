## reports pod reports-55b4fffc66-hmq7f is crash looping because the app container is OOMKilled (exit 137) at its 48Mi memory limit while loading about 200MB of report rows. The deployment has no REPORTS_BATCH_SIZE env var set, and a past incident (OPS-112) found the same failure with the same cause.

**Root cause** (high confidence, `bad_config`): The reports job loads the whole monthly dataset into memory at once. Its container limit is 48Mi (request 32Mi), and the pod's last state is OOMKilled with exit code 137. The current instance logs 'building monthly report: loading 200MB of rows'. The deployment env is empty, so REPORTS_BATCH_SIZE is unset. Per the earlier incident, the job reads that variable for its batch size and without it streams nothing, so the whole table is loaded and exceeds 48Mi. Confidence is high on the OOM mechanism and medium-high on the missing batch-size setting, since the previous container's logs are gone and the env var link comes from the past report.
**Severity:** high  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_describe_pod`: Container app (python:3.12-alpine) has limit memory 48Mi, request 32Mi, last_state and state terminated OOMKilled, exit_code 137, restarts 3, Ready False.
- `kubernetes_pod_logs`: Previous instance logs unavailable; latest instance shows 'building monthly report: loading 200MB of rows'.
- `kubernetes_describe_deployment`: reports deployment has a single revision 1 (created 2m ago), container env [] and env_from [], limit 48Mi, Available False with MinimumReplicasUnavailable.
- `kubernetes_recent_changes`: The only reports change is revision 1 created 2m ago. The checkout rollout (revision 2, DATABASE_URL removed) is a different workload and does not touch reports.
- `incidents_read`: Past report 5b0e2c4e (OPS-112, 2026-09-28): same OOMKilled at 48Mi; root cause is REPORTS_BATCH_SIZE unset, fix is REPORTS_BATCH_SIZE=1000; raising the limit only delayed the failure.

**Recommendations**
1. Set REPORTS_BATCH_SIZE=1000 in the reports deployment's manifest (env var on container app) and roll it out. This streams rows so the job stays under the limit, per the earlier incident's measurement of under 40Mi.
2. Do not just raise the 48Mi memory limit; the previous incident showed that only delays the next OOM as the table grows.
3. After the rollout, confirm the pod stays Running with 0 OOMKilled restarts and that the memory working set stays below 48Mi (container_memory_working_set_bytes for namespace demo, pod reports-*).
4. Check OPS-112 to see whether the fix was already applied to the manifests, since the same alert has come back.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "container": null, "tail_lines": 100, "previous": true}
4. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
5. `incidents_search` {"keywords": "reports OOMKilled demo", "days": 90, "limit": 5}
6. `incidents_read` {"id": "5b0e2c4e-9a51-4d1e-8f3a-2f6c7d1e0a93"}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
