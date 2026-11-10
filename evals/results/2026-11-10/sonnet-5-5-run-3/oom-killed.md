## The reports pod is crash looping because it is OOMKilled. Its memory limit is 48Mi, and the app loads about 200MB of rows at startup.

**Root cause** (high confidence, `resource_limits`): The container `app` in deployment `reports` has a 48Mi memory limit (32Mi request). On startup it logs 'building monthly report: loading 200MB of rows'. That needs far more memory than the limit allows, so the kernel kills it with exit 137 (OOMKilled). Revision 1 has been the only revision since creation and there was no rollout, so the limit was too low from the start. I did not check Prometheus memory metrics, so the actual peak usage is not measured.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: 3 restarts, last terminated OOMKilled, exit code 137, ready 0/1
- `kubernetes_describe_pod`: Container app (python:3.12-alpine) has limits.memory 48Mi, requests.memory 32Mi, and no probes or env. Events show repeated Started and BackOff.
- `kubernetes_pod_logs`: Last log line before the kill: 'building monthly report: loading 200MB of rows'
- `kubernetes_recent_changes`: reports was only created (revision 1), with no later rollout. The only rollout in the namespace is checkout rev 2, which is a different workload.

**Recommendations**
1. Raise the reports memory limit and request. Size them from the observed peak plus 25%. Loading 200MB of rows will need well above 256Mi, so start around 384-512Mi and measure.
2. Alternatively change the app to stream or paginate the rows instead of loading them all into memory.
3. Do not restart the pod. A restart does not fix an OOM crash loop.
4. Separate issues in the same namespace, not part of this alert: checkout is crash looping after revision 2 removed DATABASE_URL, and frontend has an ErrImagePull on the non-existent tag nginx:1.99.99-does-not-exist.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "reports"}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 30}
