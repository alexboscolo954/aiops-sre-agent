## The reports pod (demo/reports-55b4fffc66-hmq7f, prod-eu) is crash looping because the kernel kills it for running out of memory (OOMKilled, exit 137). Its memory limit is 48Mi, but the job's own log says it loads about 200MB of rows.

**Root cause** (high confidence, `resource_limits`): The container (python:3.12-alpine) has a memory limit of 48Mi and a request of 32Mi. On startup it logs 'building monthly report: loading 200MB of rows', about 4x the limit, so it is OOMKilled (exit 137) every time it runs. It has restarted 3 times. A rollout didn't cause this: reports is at revision 1, created about 2 minutes ago, so the limit has been too low from the first deploy. No memory metrics were available, so the real peak usage is unmeasured. The 200MB figure comes from the app's own log line.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_describe_pod`: Container app: limits memory 48Mi, requests 32Mi. State and last_state are both terminated OOMKilled with exit_code 137, restarts 3. BackOff warning event.
- `kubernetes_pod_logs`: The latest instance logs 'building monthly report: loading 200MB of rows' (previous logs were gone), far above the 48Mi limit.
- `kubernetes_recent_changes`: reports is at revision 1 (created 2m ago) with no later rollout. The only other change is checkout revision 2 removing DATABASE_URL, which has nothing to do with this OOM.

**Recommendations**
1. Raise the reports Deployment's memory limit and request to cover the working set. Loading about 200MB of rows plus the Python interpreter needs well over 200Mi, so start at roughly 256–320Mi (observed peak plus 25%, per the runbook) and change it through the deployment's source manifest/Helm values.
2. Once it's running, measure peak memory (e.g. container_memory_working_set_bytes) and adjust the limit to the observed peak plus 25%.
3. For the longer term, have the app stream or batch the rows instead of loading the whole dataset into memory.
4. Don't just restart the pod. It will be OOMKilled again until the limit changes.
5. Separately, the checkout revision 2 rollout 48s ago removed DATABASE_URL, which could break checkout. That deployment should be checked on its own.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
3. `kubernetes_pod_logs` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true}
4. `kubernetes_recent_changes` {"cluster": "prod-eu"}
5. `incidents_search` {"keywords": "reports crashloop"}
