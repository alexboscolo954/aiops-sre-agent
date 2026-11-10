## reports pod in demo keeps getting OOMKilled (exit 137, 3 restarts). It loads about 200MB of rows into a container whose memory limit is only 48Mi.

**Root cause** (high confidence, `resource_limits`): Container 'app' has a 48Mi memory limit (32Mi request). At startup the job logs 'building monthly report: loading 200MB of rows', so it needs far more memory than the limit allows, and the kernel OOM-kills it every time (exit 137). I didn't check rollout history, so I can't say whether a recent change lowered the limit or increased the data size.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f: state and last_state terminated OOMKilled exit 137, restarts 3, limits memory 48Mi, BackOff events
- `kubernetes_pod_logs`: 'building monthly report: loading 200MB of rows' right before the kill

**Recommendations**
1. Raise the reports deployment's memory limit well above the working set, for example 256Mi–512Mi, and raise the request to match.
2. Check the deployment's rollout history to see whether the limit or the data size changed recently.
3. Long term: stream or batch the rows instead of loading all 200MB into memory at once.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 50}
3. `incidents_search` {"keywords": "reports crashloop"}
