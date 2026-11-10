## reports in demo is crash looping because the kernel kills it for running out of memory (OOMKilled, exit 137). It loads about 200MB of rows into one container capped at 48Mi. REPORTS_BATCH_SIZE isn't set; past incident OPS-112 found that this is what makes the job load the whole table at once.

**Root cause** (high confidence, `bad_config`): The monthly report job loads every row at once. Its log says 'building monthly report: loading 200MB of rows', but the container's memory limit is 48Mi (request 32Mi), so every run is killed with exit 137 (3 restarts so far). The container has no env vars at all (env: [], env_from: []), so REPORTS_BATCH_SIZE is unset. Past incident 5b0e2c4e (OPS-112, 2026-09-28) found that an unset REPORTS_BATCH_SIZE makes the job load the whole table. Setting it to 1000 streamed the rows and kept memory under 40Mi. That report also says raising the memory limit on 2026-08-30 only held until the table grew. The env var behaviour comes from that past report: the current tools can't confirm it from code. The 200MB load against a 48Mi limit is confirmed now. No rollout is to blame: the deployment has a single revision (reports-55b4fffc66, created 2m ago), with the same image (python:3.12-alpine) and the same empty env as in the past incident.
**Severity:** medium  ·  **Affected:** demo/deployment/reports

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f is Running but not ready (0/1), 3 restarts, current and last state OOMKilled with exit code 137.
- `kubernetes_pod_logs`: The previous run's logs are gone; the latest run logs 'building monthly report: loading 200MB of rows' right before being killed.
- `kubernetes_describe_pod`: Container app runs python:3.12-alpine with memory limit 48Mi, request 32Mi and env: [], and its last state is OOMKilled 137. Events show a BackOff warning for restarting the failed container.
- `kubernetes_describe_deployment`: Deployment reports has a single revision (reports-55b4fffc66, 2m old) with env [] and env_from [], so REPORTS_BATCH_SIZE is not set and no earlier revision exists to roll back to.
- `incidents_read`: Past report 5b0e2c4e (OPS-112) found the same OOM at 48Mi: with REPORTS_BATCH_SIZE unset the job loads the whole table (about 200MB). Setting REPORTS_BATCH_SIZE=1000 keeps it under 40Mi, and raising the limit only delayed the next OOM.

**Recommendations**
1. In the team's manifests for deploy/reports, set REPORTS_BATCH_SIZE=1000 on the app container (the fix from OPS-112) and apply it through the normal deploy path.
2. Don't raise the memory limit as the fix: per OPS-112, the bump on 2026-08-30 only held until the table grew. Don't restart the pod either: a restart doesn't fix an OOM crash loop.
3. After the change, check that the new pod stays Running and Ready with no new OOMKilled terminations, and that memory stays below 48Mi (the past report saw under 40Mi).
4. Add the recurrence to OPS-112 and find out why the earlier fix isn't in the current manifest (the deployment was created 2m ago with no env vars), so it doesn't come back on the next redeploy.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true}
4. `incidents_search` {"keywords": "reports crashloop"}
5. `incidents_read` {"id": "5b0e2c4e-9a51-4d1e-8f3a-2f6c7d1e0a93"}
6. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
