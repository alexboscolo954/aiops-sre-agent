## demo/reports is crash looping because the kernel keeps killing it for running out of memory (OOMKilled, exit 137, 3 restarts). Its memory limit is 48Mi, but its log shows it loads about 200MB of rows to build the monthly report.

**Root cause** (high confidence, `resource_limits`): The 'app' container (python:3.12-alpine) has a memory limit of 48Mi and a request of 32Mi. On startup it logs 'building monthly report: loading 200MB of rows', which is more than four times the limit, so it is OOMKilled (exit 137) on every start. The deployment has only one revision (reports-55b4fffc66, created 2m ago), so no rollout changed anything. The limit was too small from the first deploy. Without memory metrics I can't tell a leak from a steady need, but the log itself puts the working set at about 200MB, well above 48Mi.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f is Running but 0/1 ready, with 3 restarts; its last terminated state is OOMKilled, exit_code 137.
- `kubernetes_describe_pod`: Container 'app' has memory limit 48Mi and request 32Mi, state OOMKilled (exit 137), and BackOff warning events for restarting the failed container.
- `kubernetes_pod_logs`: The previous run's logs are gone. The current run logs 'building monthly report: loading 200MB of rows' before it gets killed.
- `kubernetes_describe_deployment`: There is only one rollout revision (reports-55b4fffc66, 2m old), and its limits are memory 48Mi. Nothing changed from an earlier version.
- `runbooks_runbook_for_alert`: The oom-killed runbook says: confirm OOMKilled with exit 137, compare the limit with real usage, and raise limit and request to observed peak plus 25%. A restart only buys time.

**Recommendations**
1. Raise the memory limit on deployment demo/reports to fit the roughly 200MB dataset plus Python overhead and 25% headroom, for example limits.memory 320Mi with requests.memory around 256Mi. Do this through the deployment manifest or GitOps source.
2. Don't restart the pod: it will be OOMKilled again on the next run until the limit is raised.
3. After the change, watch working-set memory (container_memory_working_set_bytes) to check that the peak stays under the new limit. Steady growth would point to a leak instead of a sizing problem.
4. Longer term, consider having the report job stream or batch the rows instead of loading all 200MB into memory at once.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true}
4. `incidents_search` {"keywords": "reports crashloop"}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
