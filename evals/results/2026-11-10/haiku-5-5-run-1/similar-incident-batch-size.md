## The reports pod (demo/reports-55b4fffc66-hmq7f) is crash looping because its app container is OOMKilled at its 48Mi memory limit. The reports job loads the whole ~200MB table at once because REPORTS_BATCH_SIZE is not set. A past Report (OPS-112) reached the same conclusion; the current evidence supports it.

**Root cause** (medium confidence, `bad_config`): The reports container is OOMKilled (exit 137) at its 48Mi limit. Its log shows "building monthly report: loading 200MB of rows", so the job reads the entire table into memory. The deployment has no env vars (env: []), so REPORTS_BATCH_SIZE is unset. The earlier Report says the job uses that variable to batch its reads and that setting it to 1000 keeps memory under 40Mi. This is a past conclusion. Current evidence confirms the OOM and the empty env, but not the batch-size mechanism itself. Confidence is medium-high.
**Severity:** medium  ·  **Affected:** demo/deployment/reports, demo/pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: Running, 0/1 ready, 3 restarts, last_terminated OOMKilled exit 137
- `kubernetes_describe_pod`: container app: limits memory 48Mi, requests 32Mi, state OOMKilled exit 137, env [] and env_from []
- `kubernetes_pod_logs`: previous instance logs gone; latest instance shows 'building monthly report: loading 200MB of rows'
- `kubernetes_describe_deployment`: reports rollout_history has only revision 1 (created 2m ago), container env [] ; Available False, MinimumReplicasUnavailable
- `kubernetes_recent_changes`: No rollout in the window changed reports; reports revision 1 was only 'created' 2m ago, so this is not a bad rollout
- `incidents_read`: Past Report OPS-112 (2026-09-28): REPORTS_BATCH_SIZE unset causes whole-table load, OOMKilled at 48Mi; recommends setting REPORTS_BATCH_SIZE=1000 and not raising the limit again

**Recommendations**
1. Confirm with the owning team that the reports job reads REPORTS_BATCH_SIZE; the earlier Report says it does, but the current code was not inspected.
2. Set REPORTS_BATCH_SIZE=1000 on deployment demo/reports via the team's manifests (through GitOps or a reviewed change), so the job streams rows.
3. Do not just raise the 48Mi memory limit: the past Report notes that a raised limit only held until the table grew.
4. Check the pod recovers to 1/1 Ready and that memory stays under the limit over a full run.
5. The reports pod also shows FailedScheduling from an untolerated taint earlier. It is now Running, so no action is needed unless it recurs.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true}
6. `incidents_search` {"keywords": "reports OOMKilled demo"}
7. `incidents_read` {"id": "5b0e2c4e-9a51-4d1e-8f3a-2f6c7d1e0a93"}
8. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
9. `TriageReport` {"summary": "The reports pod (demo/reports-55b4fffc66-hmq7f) is crash looping because its app container is OOMKilled at its 48Mi memory limit. The reports job loads the whole ~200MB table at once because REPORTS_BATCH_SIZE is not set. A past Report (OPS-112) reached the same conclusion; the current 
