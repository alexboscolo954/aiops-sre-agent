## The reports pod is crash looping because its container is OOMKilled (exit 137) at a 48Mi memory limit. The job loads its full ~200MB input table into memory, and REPORTS_BATCH_SIZE is not set in the deployment. A past incident on the same workload found the same cause, so this is a recurring config problem, not a new rollout.

**Root cause** (medium confidence, `bad_config`): The reports container (python:3.12-alpine) has memory limit 48Mi and request 32Mi. Its last state is OOMKilled with exit code 137, and the previous-run log shows 'building monthly report: loading 200MB of rows'. The deployment's env list is empty, so REPORTS_BATCH_SIZE is unset. Per the matching past Report OPS-112, the job then reads every row at once instead of streaming in batches, which exceeds 48Mi. The deployment has only revision 1, created 2m ago, so no recent rollout caused this. The checkout DATABASE_URL change in the same window belongs to a different workload and does not explain reports.
**Severity:** high  ·  **Affected:** demo/deployment/reports, demo/pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_describe_pod`: Container app in reports-55b4fffc66-hmq7f: state and last_state both terminated OOMKilled, exit_code 137, restarts 3; limits memory 48Mi, requests memory 32Mi; env [] and env_from [].
- `kubernetes_pod_logs`: Previous instance logs were gone; the latest instance logged 'building monthly report: loading 200MB of rows' before the kill.
- `kubernetes_describe_deployment`: reports has 1 desired, 0 ready replicas; Available=False (MinimumReplicasUnavailable); single rollout_history revision 1 with env [] and memory limit 48Mi.
- `kubernetes_recent_changes`: Only reports change was revision 1 'created' 2m ago with empty diff; the DATABASE_URL removal was a checkout rollout (revision 2), a different workload with no link shown to reports.
- `incidents_read`: Past Report 5b0e2c4e-9a51-4d1e-8f3a-2f6c7d1e0a93 (OPS-112, 2026-09-28): same OOMKilled at 48Mi; root cause unset REPORTS_BATCH_SIZE, fix REPORTS_BATCH_SIZE=1000 keeps the job under 40Mi; raising the limit only delays the next OOM.

**Recommendations**
1. Set REPORTS_BATCH_SIZE=1000 on deployment reports in the team's manifests (the fix from OPS-112), then roll it out. Do not restart the pod alone, since that will not fix the crash loop.
2. Confirm in the reports code that REPORTS_BATCH_SIZE is the variable that controls batching, because this report relies on the past incident for that link.
3. After the fix, check that the pod stays Ready and that peak memory stays under 48Mi (for example at about 40Mi), then verify the deployment shows Available=True.
4. Do not raise the 48Mi memory limit as the primary fix. The past incident shows a higher limit only delays the next OOM as the table grows.
5. Track the follow-up in OPS-112 and note that the earlier 2026-08-30 limit increase did not hold.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "container": "app", "tail_lines": 50, "previous": true}
6. `incidents_search` {"keywords": "reports OOMKilled crashloop", "days": 90, "limit": 5}
7. `incidents_read` {"id": "5b0e2c4e-9a51-4d1e-8f3a-2f6c7d1e0a93"}
