## reports (demo, prod-eu) is crash looping because the kernel keeps killing it for running out of memory (OOMKilled, exit 137, 3 restarts). The container has a 48Mi memory limit, but the app logs that it is loading 200MB of rows to build the monthly report.

**Root cause** (high confidence, `resource_limits`): The memory limit is far below what the job needs. Container 'app' (python:3.12-alpine) has limits.memory=48Mi and requests.memory=32Mi. At startup it logs 'building monthly report: loading 200MB of rows', so it goes over 48Mi and is killed. The current and previous runs both ended OOMKilled with exit code 137. This is not a bad rollout: reports is still at revision 1, created about 2m ago, with no later changes. The other recent changes (checkout dropping DATABASE_URL, frontend's bad nginx tag) are separate problems that reports doesn't use. I had no metrics tool, so I couldn't measure peak memory. The roughly 200MB figure comes from the app's own log line, and the crashed run's logs were gone, so I read the latest run's.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: ready 0/1, restarts 3, state and last_terminated both OOMKilled, exit_code 137
- `kubernetes_describe_pod`: Container 'app' image python:3.12-alpine, requests memory 32Mi, limits memory 48Mi; BackOff restarting failed container (count 3)
- `kubernetes_pod_logs`: Latest run of the pod (crashed run's logs gone) logs: 'building monthly report: loading 200MB of rows'
- `kubernetes_recent_changes`: reports has only revision 1 (created 2m ago) and no later rollout, so no new revision to blame. Other changes are to checkout (rev 2 removed DATABASE_URL) and frontend.

**Recommendations**
1. Raise the memory limit and request on Deployment demo/reports to fit the roughly 200MB dataset plus Python overhead, e.g. limit 320Mi and request 256Mi. Then tune to the measured peak plus 25%, as the oom-killed runbook says.
2. Once memory metrics are available, check container_memory_working_set_bytes for reports. A steady climb points to a leak rather than a limit that's too low.
3. Longer term, have the report job stream or page through rows instead of loading all 200MB into memory at once.
4. Don't restart the pod: it will be OOMKilled again until the limit or the code changes.
5. Triage separately: checkout is crash looping after rev 2 removed DATABASE_URL, and frontend is stuck in ErrImagePull on nginx:1.99.99-does-not-exist.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "prod-eu", "namespace": "demo"}
3. `kubernetes_describe_pod` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
4. `kubernetes_pod_logs` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true}
5. `kubernetes_recent_changes` {"cluster": "prod-eu"}
6. `incidents_search` {"keywords": "reports crashloop"}
