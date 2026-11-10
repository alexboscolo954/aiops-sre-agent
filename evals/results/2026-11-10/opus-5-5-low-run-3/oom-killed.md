## reports pod in demo keeps getting OOMKilled (exit code 137, 3 restarts). Its 48Mi memory limit is far too small for a job that says it loads 200MB of rows.

**Root cause** (high confidence, `resource_limits`): The container has a 48Mi memory limit (32Mi request). Its log line 'building monthly report: loading 200MB of rows' shows it needs about 200MB or more, so the kernel kills it with OOMKilled (exit 137) on every start. I didn't check rollout history, so I can't say whether the limit or the workload changed recently.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_describe_pod`: Container app (python:3.12-alpine): limits memory 48Mi; current and last state both OOMKilled with exit 137; 3 restarts; BackOff events
- `kubernetes_pod_logs`: Latest instance's log (previous run's logs were gone): 'building monthly report: loading 200MB of rows'

**Recommendations**
1. Raise the reports deployment's memory limit to at least 256Mi (and the request to about 256Mi) in its manifest, then let it roll out.
2. Check with kubernetes_describe_deployment whether a recent revision lowered the limit or increased the data volume.
3. Over the longer term, have the report load rows in streams or batches instead of holding 200MB in memory.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 50}
3. `incidents_search` {"keywords": "reports crashloop"}
