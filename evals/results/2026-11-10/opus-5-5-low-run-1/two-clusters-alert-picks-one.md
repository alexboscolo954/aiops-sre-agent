## reports pod in demo (prod-eu) is crash looping: it gets OOMKilled (exit 137) because it loads about 200MB of rows while its memory limit is 48Mi.

**Root cause** (high confidence, `resource_limits`): The app container has a 48Mi memory limit (32Mi request). Its log says 'building monthly report: loading 200MB of rows', so it needs far more memory than the limit. It was OOMKilled with exit 137 and has restarted 3 times. I didn't check rollout history, so I can't say whether a recent change caused this.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_describe_pod`: Container app limits memory 48Mi, state terminated OOMKilled exit 137, 3 restarts, BackOff events
- `kubernetes_pod_logs`: 'building monthly report: loading 200MB of rows' (latest instance; the previous logs are gone)

**Recommendations**
1. Raise the reports memory limit and request to fit the working set (for example 512Mi limit and 256Mi request). Check the right size against actual usage.
2. Check the deployment's rollout history (kubernetes_describe_deployment) to see whether the limit or the workload changed recently.
3. Long term, stream or paginate the report rows instead of loading all 200MB into memory.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
2. `kubernetes_pod_logs` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 50}
3. `incidents_search` {"keywords": "reports crashloop"}
