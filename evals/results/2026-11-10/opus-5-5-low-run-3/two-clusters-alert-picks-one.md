## demo/reports keeps crash looping because it is OOMKilled (exit 137). The container has a 48Mi memory limit, but the job loads about 200MB of rows when it starts.

**Root cause** (high confidence, `resource_limits`): The container's memory limit is 48Mi (request 32Mi). The app logs 'building monthly report: loading 200MB of rows', so it needs far more memory than that. It was OOMKilled with exit code 137 on its last two runs and has restarted 3 times. I didn't check rollout history, so I can't say whether a recent change lowered the limit or increased the data size.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_describe_pod`: Container app has memory limit 48Mi. Its current and last state are both terminated with OOMKilled, exit 137, and it has 3 restarts plus BackOff events.
- `kubernetes_pod_logs`: Latest run logs 'building monthly report: loading 200MB of rows' (logs from the previous run were gone).

**Recommendations**
1. Raise the memory limit on the reports deployment to fit the workload, e.g. 512Mi, with a request of about 256Mi. Do it through GitOps or Helm if the deployment is managed that way.
2. Look at the deployment's rollout history to see whether a recent change lowered the limit.
3. Over the longer term, have the report stream or page rows instead of loading all 200MB into memory.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
2. `kubernetes_pod_logs` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 50}
3. `incidents_search` {"keywords": "reports crashloop"}
