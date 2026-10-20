## Pod reports-55b4fffc66-hmq7f (demo) is crash looping with OOMKilled (exit 137) and 3 restarts. Its single container has a 48Mi memory limit, while its log shows it is loading 200MB of rows to build a monthly report, so the limit is far too small for the workload. The deployment has only one revision, created 2m ago, so this is not a regression from a rollout. Separately, checkout rev 2 removed DATABASE_URL and is crashing with exit 1, and frontend is in ErrImagePull; both are outside this alert.

**Root cause** (medium confidence, `resource_limits`): The reports container has memory limit 48Mi (request 32Mi) and is terminated OOMKilled (exit 137) with restarts=3. Its previous-run log ends at 'building monthly report: loading 200MB of rows', so the job's normal data load alone is about 4x the limit. The deployment has only revision 1 (created 2m ago) with no env or image changes, so this limit was never enough for the job, and this is not a rollout regression. Confidence is medium because no Prometheus memory series was available to confirm peak usage. The previous instance's logs were gone, so only the last log line of the crashed run was seen.
**Severity:** high  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_describe_pod`: Container app in reports-55b4fffc66-hmq7f: limits memory 48Mi, requests memory 32Mi; state and last_state terminated OOMKilled, exit_code 137, restarts 3.
- `kubernetes_pod_logs`: Previous/latest instance of app logged only 'building monthly report: loading 200MB of rows' before the kill.
- `kubernetes_describe_deployment`: reports has one rollout revision (revision 1, created 2m ago, image python:3.12-alpine, no env); Available=False, MinimumReplicasUnavailable, 0/1 ready.
- `kubernetes_recent_changes`: Only changes in the window are reports revision 1 created, plus checkout rev 2 (env DATABASE_URL removed) and frontend rev 1 created; no reports rollout to blame.
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: Running, 0/1 ready, restarts 3, last_terminated OOMKilled.
- `incidents_search`: No past Reports match 'reports OOMKilled crashloop' in the last 90 days.

**Recommendations**
1. Confirm the real peak memory of the report job (for example, run it with a higher limit or check container_memory_working_set_bytes for pod reports-55b4fffc66-hmq7f if Prometheus is available).
2. Raise the reports container memory limit (and request) well above the 200MB data load, for example to about 256Mi or more, or reduce how much data the job loads at once (stream or chunk the rows). Apply through the deployment spec, not a restart.
3. Watch the reports pod for OOMKilled after the change; if it still gets killed, check for a memory leak as the job runs.
4. Separately, look at demo/checkout: revision 2 removed the DATABASE_URL env var and the pod exits with code 1. Restoring DATABASE_URL or rolling back to revision 1 is the likely fix.
5. Separately, frontend-6f6b4986b9-hxdf2 uses image nginx:1.99.99-does-not-exist, which does not exist. Correct the image tag.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "container": "app", "previous": true, "tail_lines": 30}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
6. `incidents_search` {"keywords": "reports OOMKilled crashloop", "days": 90, "limit": 5}
7. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": ""}
