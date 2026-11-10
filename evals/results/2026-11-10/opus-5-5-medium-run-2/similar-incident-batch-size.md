## demo/reports (pod reports-55b4fffc66-hmq7f) is crash looping because it is OOMKilled (exit 137) at its 48Mi memory limit. Each start, the monthly report loads about 200MB of rows into memory at once. The container has no env vars, so REPORTS_BATCH_SIZE is not set. A past incident (OPS-112) found the same cause.

**Root cause** (high confidence, `bad_config`): The reports container keeps getting OOMKilled (exit 137, 3 restarts) at its 48Mi limit. Its log says 'building monthly report: loading 200MB of rows', which is far more than 48Mi. The deployment (revision 1, created 2m ago) runs with env: [] and envFrom: [], so REPORTS_BATCH_SIZE is unset. Past incident OPS-112 (2026-09-28) found that with this variable unset, the job loads the whole table at once. It also found that REPORTS_BATCH_SIZE=1000 streams the rows and keeps the job under 40Mi, and that raising the limit on 2026-08-30 only held until the table grew. Current tools confirm the OOM, the 48Mi limit, the 200MB load and the empty env. What the variable does is known only from that past report. The checkout rollout that removed DATABASE_URL 48s ago is a separate change. Nothing seen links it to reports.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_describe_pod`: Container app in reports-55b4fffc66-hmq7f: state and last_state both terminated OOMKilled, exit code 137, 3 restarts; limits memory 48Mi, requests 32Mi; env [] and env_from []; BackOff warning events.
- `kubernetes_pod_logs`: 'building monthly report: loading 200MB of rows' (previous instance's logs were gone, so this is the latest instance).
- `kubernetes_describe_deployment`: reports is at revision 1 only (created 2m ago), image python:3.12-alpine, env [] (no REPORTS_BATCH_SIZE), 0/1 ready, Available=False.
- `kubernetes_recent_changes`: No reports change other than its creation. The only other rollout is checkout rev 2, which removed DATABASE_URL and is not linked to reports.
- `incidents_read`: Past report 5b0e2c4e (OPS-112): same OOM at 48Mi caused by REPORTS_BATCH_SIZE being unset. Fix: set REPORTS_BATCH_SIZE=1000. Raising the limit before only delayed the next OOM.

**Recommendations**
1. Set REPORTS_BATCH_SIZE=1000 on the reports deployment in the team's manifests or GitOps source, then roll it out.
2. Don't raise the memory limit as the fix: OPS-112 shows that only delays the next OOM as the table grows. Don't restart the pod either, because restarting doesn't fix a crash loop.
3. After the rollout, check that the pod stays Running with no new OOMKilled restarts and that memory use stays under 48Mi (about 40Mi is expected).
4. Find out why the earlier fix from OPS-112 isn't in the current manifest (env is empty). It may have been reverted or never committed. Add REPORTS_BATCH_SIZE to the source of truth so it isn't lost again.
5. Separately, look into the checkout rollout that removed DATABASE_URL; it may cause its own alert.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 50}
4. `incidents_search` {"keywords": "reports crashloop"}
5. `incidents_read` {"id": "5b0e2c4e-9a51-4d1e-8f3a-2f6c7d1e0a93"}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
7. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
