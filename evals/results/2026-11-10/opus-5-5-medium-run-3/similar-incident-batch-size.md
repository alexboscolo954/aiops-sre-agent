## reports (demo) is crash looping because the container is OOMKilled (exit 137) at its 48Mi memory limit while the monthly report loads about 200MB of rows. This matches past incident OPS-112: REPORTS_BATCH_SIZE is not set, so the job loads the whole table into memory at once.

**Root cause** (high confidence, `bad_config`): The reports container has a 48Mi memory limit and no env vars at all (env: [], envFrom: []), so REPORTS_BATCH_SIZE is not set. Its log says 'building monthly report: loading 200MB of rows', and the kernel kills it (OOMKilled, exit 137, 3 restarts). Past incident 5b0e2c4e (OPS-112) says the job loads the whole table when REPORTS_BATCH_SIZE is unset, and that setting it to 1000 streams the rows and keeps the job under 40Mi. That report also says raising the limit on 2026-08-30 only held until the table grew. The current pod state and log match that report exactly. The deployment has only revision 1 (created 2m ago, missing the env var), so this is a recurrence of the same config gap, not a regression from an earlier working revision. No Prometheus tool was available, so I could not confirm the memory usage curve.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f container app: state and last_state terminated OOMKilled, exit code 137, restarts 3, memory limit 48Mi (request 32Mi), env [] and envFrom []
- `kubernetes_pod_logs`: 'building monthly report: loading 200MB of rows' (previous logs were gone, so this is the latest instance)
- `kubernetes_describe_deployment`: deploy/reports has only revision 1 (reports-55b4fffc66, 2m old), image python:3.12-alpine, limits memory 48Mi, env [] (no REPORTS_BATCH_SIZE), 0/1 ready
- `incidents_read`: Past report 5b0e2c4e (2026-09-28, OPS-112): same OOMKill at 48Mi caused by REPORTS_BATCH_SIZE being unset; REPORTS_BATCH_SIZE=1000 keeps the job under 40Mi; raising the limit only delayed the next OOM

**Recommendations**
1. Set REPORTS_BATCH_SIZE=1000 on deploy/reports in the team's manifests (GitOps/source of truth) and redeploy. Confirm the pod stays Running and is not OOMKilled.
2. Don't just raise the memory limit or restart the pod. A previous limit raise only delayed the next OOM, and a restart doesn't fix a crash loop.
3. Find out why the manifest went out without REPORTS_BATCH_SIZE even though OPS-112 recommended it (for example, the fix never got merged or the deployment was recreated from an old manifest), and link this occurrence to OPS-112.
4. Consider making the app default to a bounded batch size when the env var is missing, so a missing setting can't load the whole table again.

Runbook: `oom-killed`

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 50}
3. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
4. `incidents_search` {"keywords": "reports crashloop"}
5. `incidents_read` {"id": "5b0e2c4e-9a51-4d1e-8f3a-2f6c7d1e0a93"}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
