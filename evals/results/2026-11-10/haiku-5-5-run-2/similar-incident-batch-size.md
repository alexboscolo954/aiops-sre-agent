## reports pod is OOMKilled repeatedly at its 48Mi memory limit (exit 137) while building the monthly report, which loads about 200MB of rows at once. The reports deployment has no env vars set, so REPORTS_BATCH_SIZE is unset. A past incident on the same workload reached the same root cause with high confidence.

**Root cause** (medium confidence, `bad_config`): The reports job has no REPORTS_BATCH_SIZE env var (deployment env is empty), so it loads the whole table into memory. The container is limited to 48Mi, and the kernel OOM-kills it (last state OOMKilled, exit 137, 3 restarts). The current revision 1 was created 2m ago and was not a regression: the same config existed from creation. The past incident (OPS-112) concluded the same and noted that raising the limit only delays the next kill. I did not verify the batch size fix in code, so that part relies on the past incident.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: restarts 3, app last terminated OOMKilled, exit code 137
- `kubernetes_describe_pod`: container app limits memory 48Mi, requests 32Mi, env [] and env_from []; last_state OOMKilled exit 137
- `kubernetes_pod_logs`: previous logs gone; latest instance logs: 'building monthly report: loading 200MB of rows'
- `kubernetes_describe_deployment`: reports rollout revision 1 only, created 2m ago, config app env [] ; Available False MinimumReplicasUnavailable
- `kubernetes_recent_changes`: reports revision 1 'created' with empty diff; no later rollout of reports
- `incidents_read`: Past report 5b0e2c4e (OPS-112): same workload OOMKilled at 48Mi because REPORTS_BATCH_SIZE unset; recommends setting REPORTS_BATCH_SIZE=1000 and not raising the limit

**Recommendations**
1. Set REPORTS_BATCH_SIZE=1000 on deploy/reports in the team's manifests (GitOps source), then roll out. This is a config change, not a restart.
2. Do not raise the 48Mi memory limit as the fix; it only delays the next OOM as the table grows.
3. Confirm the batch size variable name and its effect in the reports code or docs before rollout, since the past incident is the only source for it.
4. Track the OPS-112 Jira issue; it was linked to a previous occurrence.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 50}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
7. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
8. `incidents_search` {"keywords": "reports OOMKilled demo"}
9. `incidents_read` {"id": "5b0e2c4e-9a51-4d1e-8f3a-2f6c7d1e0a93"}
10. `TriageReport` {"summary": "reports pod is OOMKilled repeatedly at its 48Mi memory limit (exit 137) while building the monthly report, which loads about 200MB of rows at once. The reports deployment has no env vars set, so REPORTS_BATCH_SIZE is unset. A past incident on the same workload reached the same root caus
