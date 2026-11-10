## The reports pod in demo (deploy/reports) is crash looping. It is OOMKilled (exit 137) at its 48Mi memory limit while it builds the monthly report, which loads about 200MB of rows. The container has no env vars at all, so REPORTS_BATCH_SIZE is not set. A past incident (OPS-112) traced the same failure to this missing setting.

**Root cause** (high confidence, `bad_config`): The reports container has a 48Mi memory limit (32Mi request) and its env is empty. The log line just before the kill says 'building monthly report: loading 200MB of rows', so the job tries to hold about 200MB in a 48Mi container and the kernel kills it. All three restarts end in OOMKilled, exit 137. Past report 5b0e2c4e (OPS-112) says the job reads its batch size from REPORTS_BATCH_SIZE. When that is unset it loads the whole table at once. With REPORTS_BATCH_SIZE=1000 it streams rows and stays under 40Mi. That report also says raising the limit on 2026-08-30 only held until the table grew. Current tools confirm the variable is unset, but the variable's behaviour comes from that past report, not from anything I saw today. No rollout is to blame: the deployment has a single revision (reports-55b4fffc66, created about 2m ago) and has never been healthy.
**Severity:** medium  ·  **Affected:** demo/deployment/reports

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: Running, 0/1 ready, 3 restarts, last terminated OOMKilled with exit code 137
- `kubernetes_describe_pod`: Container app (python:3.12-alpine): memory limit 48Mi, request 32Mi, env [] and env_from []; state and last_state both OOMKilled 137; BackOff restarting failed container
- `kubernetes_pod_logs`: Only the latest instance's logs were left (previous ones gone): 'building monthly report: loading 200MB of rows'
- `kubernetes_describe_deployment`: deploy/reports has a single revision 1 (reports-55b4fffc66, created 2m ago), env [] with no REPORTS_BATCH_SIZE, limits 48Mi, Available=False
- `incidents_read`: Past report 5b0e2c4e (OPS-112, 2026-09-28): same OOMKilled at 48Mi caused by REPORTS_BATCH_SIZE being unset; REPORTS_BATCH_SIZE=1000 keeps the job under 40Mi; raising the limit earlier only delayed the next OOM

**Recommendations**
1. Set REPORTS_BATCH_SIZE=1000 on deploy/reports in the team's manifests (or GitOps source) and roll it out, so the monthly report streams rows instead of loading about 200MB at once.
2. Don't raise the memory limit as the fix. OPS-112 says that only held until the table grew. And don't restart the pod: that won't fix the crash loop.
3. After the change, check that the new pod stays Ready with no new OOMKilled terminations. If metrics are available, confirm working-set memory stays under the 48Mi limit.
4. Find out why the OPS-112 fix isn't in the current deployment, which is a fresh revision 1 created about 2m ago with empty env. The manifest may have been recreated from an old source. Make the setting permanent so it doesn't come back.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true}
4. `incidents_search` {"keywords": "reports crashloop"}
5. `incidents_read` {"id": "5b0e2c4e-9a51-4d1e-8f3a-2f6c7d1e0a93"}
6. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
