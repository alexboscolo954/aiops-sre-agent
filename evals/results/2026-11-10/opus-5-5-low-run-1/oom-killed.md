## reports pod in demo is crash looping: the app container gets OOMKilled (exit 137) because its 48Mi memory limit is far below what the job loads (it logs 'loading 200MB of rows').

**Root cause** (high confidence, `resource_limits`): Container 'app' has a 48Mi memory limit (32Mi request), but the monthly report build loads about 200MB of rows into memory. The kernel OOM-kills it every time (exit 137, 3 restarts). I did not check rollout history, so I can't rule out a recent change to the limit or the workload.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_describe_pod`: state and last_state are terminated OOMKilled, exit 137, 3 restarts; limits memory 48Mi, requests 32Mi; BackOff events
- `kubernetes_pod_logs`: 'building monthly report: loading 200MB of rows' right before the kill

**Recommendations**
1. Raise the reports memory limit to about 256-512Mi, above the ~200MB working set plus Python overhead, in the deployment manifest and roll it out.
2. Longer term, have the report stream or batch its rows instead of loading all 200MB at once.
3. Check the reports deployment's rollout history to see whether a recent revision lowered the limit or increased the data volume.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 50}
3. `incidents_search` {"keywords": "reports"}
