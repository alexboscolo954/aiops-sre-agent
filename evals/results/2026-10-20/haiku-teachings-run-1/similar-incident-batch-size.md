## Pod reports-55b4fffc66-hmq7f is crash looping because the app container is OOMKilled (exit 137) at its 48Mi memory limit. The job loads its full 200MB table into memory, and the reports deployment sets no env vars, so REPORTS_BATCH_SIZE is unset. A past incident (OPS-112) found the same cause, so this is a recurrence and raising the limit again would only delay the next kill.

**Root cause** (high confidence, `bad_config`): The reports container runs with memory limit 48Mi (request 32Mi) and its env is empty, so REPORTS_BATCH_SIZE is not set. The current log shows 'building monthly report: loading 200MB of rows', so the job loads every row at once, far above 48Mi, and the kernel OOM-kills it (last state OOMKilled, exit 137, restarts 3). The deployment has only one revision (revision 1, created 2m ago), so no rollout introduced this. The past incident 5b0e2c4e (high confidence) reached the same conclusion, and its recommended fix (REPORTS_BATCH_SIZE=1000, which streams rows and keeps the job under 40Mi) has not been applied, since the env is still empty.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_describe_pod`: Container app (python:3.12-alpine) has limits memory 48Mi, requests memory 32Mi, env [] and env_from []; state and last_state are OOMKilled with exit_code 137; restarts 3.
- `kubernetes_pod_logs`: Previous logs gone; latest instance shows 'building monthly report: loading 200MB of rows' before the kill.
- `kubernetes_describe_deployment`: reports has one revision (revision 1, created 2m ago); container env is [] so REPORTS_BATCH_SIZE is not set; Available=False, MinimumReplicasUnavailable, ready 0 of desired 1.
- `kubernetes_recent_changes`: Only reports rollout is revision 1 'created'. The checkout change (DATABASE_URL removed, revision 2) is a different workload with no dependency link to reports, so it is not the cause.
- `incidents_read`: Past report 5b0e2c4e (OPS-112, 2026-09-28): same symptom, OOMKilled at 48Mi; root cause REPORTS_BATCH_SIZE unset so the whole table loads; the limit was raised on 2026-08-30 and only delayed the failure; REPORTS_BATCH_SIZE=1000 keeps the job under 40Mi.
- `runbooks_runbook_for_alert`: KubePodCrashLooping maps to pod-crashlooping, which routes OOMKilled pods to the oom-killed runbook: compare the limit with real usage and fix the config or the limit.

**Recommendations**
1. Set REPORTS_BATCH_SIZE=1000 on deployment reports in the team's manifests (the fix from OPS-112) and roll it out. This is a config change, so it needs human approval.
2. Do not raise the 48Mi memory limit as the main fix. The past incident shows a larger limit only delays the next OOM as the table grows. Consider a moderate limit increase only as a short-term buffer, after the batch fix.
3. After the rollout, confirm the pod stays Running with 0 new OOMKilled restarts and that memory stays under about 40Mi.
4. Check OPS-112: the earlier fix was recommended but the env is still unset, so find out why it was not applied to the manifests and make sure it is tracked in source control.
5. Ignore the FailedScheduling taint warning and the slow 1m21s image pull for this alert. They are not what is crashing the pod.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "container": "app", "previous": true, "tail_lines": 50}
6. `incidents_search` {"keywords": "reports OOMKilled memory limit", "days": 90, "limit": 5}
7. `incidents_read` {"id": "5b0e2c4e-9a51-4d1e-8f3a-2f6c7d1e0a93"}
