## The reports deployment in demo is down (0/1 ready). Its only pod, reports-55b4fffc66-hmq7f, keeps getting OOMKilled (exit 137, 3 restarts) because the app loads about 200MB of rows into a container whose memory limit is 48Mi.

**Root cause** (high confidence, `resource_limits`): The memory limit on container 'app' (python:3.12-alpine, request 32Mi, limit 48Mi) is far below what the job needs. The log shows 'building monthly report: loading 200MB of rows' just before each kill, and the kernel ends the container with OOMKilled (exit 137) every time. Revision 1 is the only revision and it has never been ready, so no rollout broke a working version: the limit was too low from the start. Without metrics I can't confirm actual peak usage, but loading 200MB of data means the peak is at least about 200MB plus Python's own overhead.
**Severity:** high  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f is Running but 0/1 ready, 3 restarts; current and last state both OOMKilled, exit code 137
- `kubernetes_describe_pod`: Container app: image python:3.12-alpine, requests memory 32Mi, limits memory 48Mi; BackOff warning events while restarting
- `kubernetes_pod_logs`: Latest instance log (previous logs gone): 'building monthly report: loading 200MB of rows', printed just before the OOM kill
- `kubernetes_describe_deployment`: Only one revision (reports-55b4fffc66, created 2m ago) with the same 48Mi limit; condition Available=False, MinimumReplicasUnavailable

**Recommendations**
1. Raise the memory limit and request on the reports deployment to fit the real working set: at least about 256Mi request and 320Mi limit, given the 200MB dataset plus Python overhead. Then tune it to the observed peak plus 25%, as the oom-killed runbook says.
2. Watch memory after the change (for example container_memory_working_set_bytes, if Prometheus is available) to check the new limit holds and usage isn't still growing.
3. Long term, have the report job stream or batch rows instead of loading all 200MB into memory at once.
4. Don't just restart the pod: it will be OOMKilled again until the limit is raised.
5. Separate issues in demo that aren't part of this alert: checkout is crash looping with exit 1, and frontend is stuck in ErrImagePull because the tag nginx:1.99.99-does-not-exist doesn't exist.

Runbook: `oom-killed`

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
2. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
3. `incidents_search` {"keywords": "reports crashloop"}
4. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 50}
