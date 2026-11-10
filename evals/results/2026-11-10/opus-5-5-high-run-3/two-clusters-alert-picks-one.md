## Pod demo/reports-55b4fffc66-hmq7f keeps getting OOMKilled (exit 137, 3 restarts). Its memory limit is 48Mi, but the app logs that it is loading 200MB of rows for the monthly report. The limit is far too small for this job, so the deployment has no ready replicas.

**Root cause** (high confidence, `resource_limits`): The container 'app' (python:3.12-alpine) has a 48Mi memory limit and a 32Mi request. When it starts, it logs 'building monthly report: loading 200MB of rows'. That is roughly 4x the limit, so the kernel kills it with OOMKilled (exit 137) on every start. The deployment was created about 2m ago and has only revision 1. No later rollout changed it, so the limit has been too low from the start; nothing regressed. The working-set size is an estimate from the log line because no metrics tool was available.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: Running, 0/1 ready, 3 restarts, current and last termination OOMKilled, exit_code 137
- `kubernetes_describe_pod`: Container app (python:3.12-alpine) has memory request 32Mi and limit 48Mi; BackOff warning events show the failed container restarting
- `kubernetes_pod_logs`: Latest instance logs 'building monthly report: loading 200MB of rows' before being killed (the previous instance's logs were gone)
- `kubernetes_describe_deployment`: reports has only rollout revision 1 (created 2m ago) with the 48Mi limit; 0/1 ready, Available=False (MinimumReplicasUnavailable)
- `kubernetes_recent_changes`: The only change to reports was its creation 2m ago. The one rollout in the last hour was checkout rev 2 (DATABASE_URL removed), which is unrelated to reports

**Recommendations**
1. Raise the memory limit and request on Deployment demo/reports to fit the dataset, e.g. limit about 320Mi (200MB of rows plus Python overhead plus 25% headroom) and request about 256Mi. Apply it through the deployment's source of truth (manifest or Helm values).
2. Once the new pod is running, check its real peak memory (e.g. container_memory_working_set_bytes or kubectl top) and set the limit to the observed peak plus 25%, as the oom-killed runbook says.
3. Longer term, make the report job stream or batch rows so it doesn't load the whole 200MB into memory at once.
4. Don't restart the pod as a fix: it will be OOMKilled again until the limit changes.
5. Unrelated issues in the same namespace that need separate triage: checkout is crash looping after rev 2 removed DATABASE_URL, and frontend is stuck in ErrImagePull because the image tag nginx:1.99.99-does-not-exist doesn't exist.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "prod-eu", "namespace": "demo"}
3. `incidents_search` {"keywords": "reports"}
4. `kubernetes_describe_pod` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
5. `kubernetes_pod_logs` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 50}
6. `kubernetes_describe_deployment` {"cluster": "prod-eu", "namespace": "demo", "name": "reports"}
7. `kubernetes_recent_changes` {"cluster": "prod-eu", "since_minutes": 60}
