## The reports pod (demo/reports-55b4fffc66-hmq7f) is crash looping because it keeps being OOMKilled (exit code 137, 3 restarts). Its memory limit is 48Mi, but its log says it is loading 200MB of rows to build the monthly report.

**Root cause** (high confidence, `resource_limits`): The memory limit is far too small for the job. The deployment's container 'app' (python:3.12-alpine) has a 48Mi memory limit and a 32Mi request. Its log says 'building monthly report: loading 200MB of rows', which is roughly four times the limit, so the kernel kills it every time (last terminated OOMKilled, exit 137). The deployment has only one revision (created 2m ago), so no earlier working version exists and no change to roll back. This setup has been under-sized since it was created. I had no Prometheus data, so I couldn't measure actual peak memory. The 200MB figure comes from the app's own log line.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: Running 0/1, 3 restarts, last terminated OOMKilled with exit code 137
- `kubernetes_pod_logs`: reports pod log (latest instance; previous logs were gone): 'building monthly report: loading 200MB of rows'
- `kubernetes_describe_deployment`: reports container 'app' has memory limit 48Mi and request 32Mi; only revision 1 (created 2m ago), Available=False

**Recommendations**
1. Raise the memory limit and request on Deployment demo/reports to fit the roughly 200MB dataset plus Python overhead and 25% headroom, e.g. limit about 320Mi and request about 256Mi. Then confirm the pod stays Ready with no new OOMKilled restarts.
2. If memory metrics become available, check container_memory_working_set_bytes for the reports pod and set the limit to the observed peak plus 25%.
3. Longer term, have the report job stream or batch rows instead of loading all 200MB into memory at once.
4. Don't restart the pod: it will be OOMKilled again until the limit or the memory use changes.
5. Unrelated issues in the same namespace, worth triaging separately: checkout is crash looping with exit 1, and frontend can't pull the image nginx:1.99.99-does-not-exist.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true}
4. `incidents_search` {"keywords": "reports crashloop"}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
