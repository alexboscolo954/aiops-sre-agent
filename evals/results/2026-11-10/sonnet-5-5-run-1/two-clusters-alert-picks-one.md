## The reports pod in demo on prod-eu is crash looping because it is OOMKilled (exit 137). Its memory limit is 48Mi, and the app loads about 200MB of rows at startup.

**Root cause** (high confidence, `resource_limits`): The reports container (python:3.12-alpine) has a 48Mi memory limit and a 32Mi request. Its log says "building monthly report: loading 200MB of rows", so the workload needs several times the limit and the kernel OOM kills it on every start. The deployment is still at revision 1 with no rollout since creation, so this is a sizing problem and not a regression. It could also be an app issue, since the code loads the whole dataset into memory. That is inferred from the log line, not measured.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: last terminated OOMKilled, exit code 137, 3 restarts, ready 0/1
- `kubernetes_describe_pod`: container app limits memory 48Mi, requests 32Mi; BackOff events; no probes; no env config
- `kubernetes_pod_logs`: "building monthly report: loading 200MB of rows" (the only log line, from the latest instance since the previous one's logs were gone)
- `kubernetes_recent_changes`: reports has only revision 1 (created 2m ago) with no later rollout. The checkout and frontend problems are separate workloads.

**Recommendations**
1. Raise the reports memory limit and request through the deployment manifest or GitOps source. The need is at least 200MB plus overhead, so a limit of about 384Mi is a reasonable start. Confirm the real peak with container_memory_working_set_bytes.
2. Longer term, change the report job to stream or paginate rows instead of loading 200MB at once.
3. Don't just restart the pod. A restart doesn't fix an OOM crash loop.
4. Note that checkout (DATABASE_URL env var removed in revision 2) and frontend (nonexistent image tag nginx:1.99.99-does-not-exist) are failing in the same namespace for unrelated reasons and need their own triage.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "prod-eu", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "prod-eu"}
4. `incidents_search` {"keywords": "reports"}
5. `kubernetes_describe_pod` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
6. `kubernetes_pod_logs` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 30}
