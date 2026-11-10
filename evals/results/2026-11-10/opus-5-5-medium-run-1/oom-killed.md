## The pod demo/reports-55b4fffc66-hmq7f is crash looping because the kernel keeps killing it for using too much memory (OOMKilled, exit 137, 3 restarts). Its memory limit is 48Mi, but on startup the app logs that it is loading 200MB of rows.

**Root cause** (high confidence, `resource_limits`): The memory limit is far too small for what the job does. The container's limit is 48Mi (request 32Mi), and the log shows 'building monthly report: loading 200MB of rows', so it goes over the limit right away and is killed with OOMKilled, exit code 137. A recent change is not the cause: the deployment has only revision 1, created about 2m ago, so it has never run with this limit. It looks like it was sized wrong from the start. I had no metrics tool, so actual peak memory use was not measured.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: ready 0/1, 3 restarts, last terminated OOMKilled with exit code 137
- `kubernetes_pod_logs`: Latest instance logs (the previous instance's logs were gone): 'building monthly report: loading 200MB of rows'
- `kubernetes_describe_deployment`: reports container app (python:3.12-alpine): memory limit 48Mi, request 32Mi; only one revision (reports-55b4fffc66, created 2m ago); Available=False

**Recommendations**
1. Raise the memory limit and request on deployment demo/reports to fit the roughly 200MB working set plus headroom, e.g. limit 320Mi and request 256Mi. Per the runbook, refine this to observed peak plus 25% once memory metrics are available.
2. Alternatively, change the report job to stream or page through the rows instead of loading all 200MB into memory at once.
3. Do not restart the pod: it will just be OOMKilled again until the limit or the code changes.
4. Unrelated issues seen in the same namespace, worth separate triage: checkout is crash looping with Error exit 1, and frontend fails to pull the image nginx:1.99.99-does-not-exist.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 50}
4. `incidents_search` {"keywords": "reports crashloop"}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
