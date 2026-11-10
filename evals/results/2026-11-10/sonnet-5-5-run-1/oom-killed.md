## The reports pod is crash looping because its container is OOMKilled (exit 137). The memory limit is 48Mi, and the app loads about 200MB of rows while building a report.

**Root cause** (high confidence, `resource_limits`): The reports container (python:3.12-alpine) has a memory limit of 48Mi (request 32Mi). On startup it logs "building monthly report: loading 200MB of rows", which is far more than the limit. The kernel OOM-kills it every time (last terminated: OOMKilled, exit 137, 3 restarts). reports has only revision 1, so no rollout caused this. The limit looks undersized for the workload, but the code could also be loading too much data at once.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: app last terminated OOMKilled, exit code 137, restarts 3, ready 0/1
- `kubernetes_describe_pod`: Container app has memory limit 48Mi and request 32Mi, no env. BackOff warning events. Container started and killed repeatedly.
- `kubernetes_pod_logs`: Latest instance log (previous instance's logs were gone): "building monthly report: loading 200MB of rows", which is well above the 48Mi limit
- `kubernetes_recent_changes`: reports only has revision 1 (created ~2m ago), with no later rollout. The only rollout is checkout rev 2, which is unrelated.

**Recommendations**
1. Raise the reports memory limit and request to cover the real peak plus 25%. Loading 200MB of rows needs roughly 256Mi or more, so check the actual peak first.
2. Or change the job to stream or paginate rows instead of loading 200MB at once, so it fits a small limit.
3. Don't just restart the pod. A restart does not fix an OOM crash loop.
4. Separate issues in the demo namespace: checkout is crash looping after rev 2 removed DATABASE_URL, and frontend has an ErrImagePull on nginx:1.99.99-does-not-exist. Triage these on their own.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "reports"}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 30}
