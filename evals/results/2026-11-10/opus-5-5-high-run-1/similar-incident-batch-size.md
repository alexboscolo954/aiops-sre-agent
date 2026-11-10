## The reports pod in demo (reports-55b4fffc66-hmq7f) is crash looping because it gets OOMKilled (exit 137) at its 48Mi memory limit. Its log shows it loading about 200MB of rows into memory at once. The container has no env vars at all, so REPORTS_BATCH_SIZE is not set. A past incident (OPS-112) blamed the same missing variable.

**Root cause** (medium confidence, `bad_config`): The reports container is limited to 48Mi of memory (request 32Mi). On each start it logs 'building monthly report: loading 200MB of rows' and is then OOMKilled (exit code 137), 3 restarts so far. The deployment and pod both show env: [] and env_from: [], so REPORTS_BATCH_SIZE is missing. Past incident 5b0e2c4e (OPS-112, 2026-09-28) found the same thing: with REPORTS_BATCH_SIZE unset, the job loads the whole table into memory instead of streaming it. That report says setting REPORTS_BATCH_SIZE=1000 kept the job under 40Mi, and that raising the limit on 2026-08-30 only worked until the table grew. Everything the current tools show matches that report, but none of them can confirm the env var behaviour itself; that part comes only from the past report. This is not a bad rollout: the deployment has a single revision (rev 1, created 2m ago).
**Severity:** medium  ·  **Affected:** demo/deployment/reports

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: Running, 0/1 ready, 3 restarts, last terminated OOMKilled with exit code 137.
- `kubernetes_describe_pod`: Container app (python:3.12-alpine) has memory limit 48Mi, request 32Mi, env [] and env_from []; state and last_state are both OOMKilled 137; BackOff warning events.
- `kubernetes_pod_logs`: Latest instance logs (previous run's logs were gone): 'building monthly report: loading 200MB of rows', far more than the 48Mi limit.
- `kubernetes_describe_deployment`: Deployment reports has a single revision (rev 1, reports-55b4fffc66, created 2m ago) with env [] (no REPORTS_BATCH_SIZE); 0/1 ready, MinimumReplicasUnavailable.
- `incidents_read`: Past report 5b0e2c4e (OPS-112, 2026-09-28): same OOMKilled at 48Mi caused by REPORTS_BATCH_SIZE being unset; setting it to 1000 streams the rows and keeps the job under 40Mi; raising the limit earlier only delayed the next OOM.

**Recommendations**
1. Set REPORTS_BATCH_SIZE=1000 on deploy/reports in the team's manifests or GitOps source (not with an ad-hoc kubectl edit), then roll out and watch the pod's memory and restart count.
2. Don't raise the memory limit as the fix: the past incident shows it only delays the next OOM as the table grows. Restarting won't help either.
3. Ask the reports owners why the REPORTS_BATCH_SIZE fix from OPS-112 isn't in this deployment, which looks newly created (rev 1, 2m old), and make the job default to batched reads when the variable is unset.
4. This alert didn't cover them, but checkout is also crash looping (Error, exit 1) and frontend has ErrImagePull on nginx:1.99.99-does-not-exist in the same namespace. Triage those separately.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true}
4. `incidents_search` {"keywords": "reports"}
5. `incidents_read` {"id": "5b0e2c4e-9a51-4d1e-8f3a-2f6c7d1e0a93"}
6. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
