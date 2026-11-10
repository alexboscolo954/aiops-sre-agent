## The reports pod reports-55b4fffc66-hmq7f in demo on prod-eu is crash looping because the kernel keeps killing it for running out of memory (OOMKilled, exit 137, 3 restarts so far). On startup it loads about 200MB of rows, but its memory limit is 48Mi.

**Root cause** (high confidence, `resource_limits`): The app container's memory limit is 48Mi (request 32Mi). On startup its log says it is "building monthly report: loading 200MB of rows", which is about 4 times the limit, so the kernel kills it on every attempt. Both the current and the last state are OOMKilled with exit code 137. This is revision 1 of the reports deployment, created about 2 minutes ago, so no earlier working revision exists and a rollback is not an option. The checkout rollout about 48s ago (DATABASE_URL removed) is a different workload, and nothing seen links it to these memory kills. The heap-growth check from the runbook was not done because there is no metrics tool. The log line points to a limit that is simply too small, not a leak.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_describe_pod`: Pod reports-55b4fffc66-hmq7f, container app (python:3.12-alpine): limits memory 48Mi, requests 32Mi; state terminated OOMKilled exit 137, last_state OOMKilled exit 137, restarts 3, BackOff events
- `kubernetes_pod_logs`: Latest instance log (the previous run's logs were gone): "building monthly report: loading 200MB of rows", about 4x the 48Mi limit
- `kubernetes_recent_changes`: reports revision 1 was created about 2m ago (no earlier revision). The only rollout is checkout revision 2 (DATABASE_URL removed), a different workload
- `runbooks_runbook_for_alert`: pod-crashlooping runbook says an OOMKilled exit 137 goes to the oom-killed runbook, whose fix is to raise the limit and request to peak plus 25% or fix the leak; restarting only buys time

**Recommendations**
1. Raise the memory limit on the reports deployment's app container to cover its real working set. Loading 200MB of rows plus Python overhead needs at least about 256Mi, ideally about 320Mi. Raise the request to match, then roll out.
2. Once it is running, measure peak memory (container_memory_working_set_bytes) and set the limit to that peak plus 25%, as the oom-killed runbook says.
3. Longer term, have the report job stream or page through the rows instead of loading all 200MB into memory at once.
4. Don't restart the pod: it will be OOMKilled again until the limit changes.
5. Look at the separate checkout rollout (revision 2 removed DATABASE_URL) in case it causes its own alerts. It is not the cause of this one.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
3. `kubernetes_pod_logs` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 100}
4. `kubernetes_recent_changes` {"cluster": "prod-eu"}
5. `incidents_search` {"keywords": "reports crashloop"}
