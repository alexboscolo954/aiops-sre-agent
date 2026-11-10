## The reports pod in demo is crash looping because it keeps getting OOMKilled (exit 137). On startup it loads about 200MB of rows, but its container has a 48Mi memory limit.

**Root cause** (high confidence, `resource_limits`): Container 'app' (python:3.12-alpine) has limits.memory=48Mi and requests.memory=32Mi. Its only log line is 'building monthly report: loading 200MB of rows'. That is roughly 4x the limit, so the kernel kills it with OOMKilled (exit 137) on every start: 3 restarts so far, and both the current and previous state are OOMKilled. The deployment has only revision 1, created about 2m ago, so no earlier working revision broke. The memory limit was simply never big enough for this job.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f container app: state terminated OOMKilled exit 137, last_state OOMKilled exit 137, restarts 3; limits memory 48Mi, requests 32Mi; BackOff warning events
- `kubernetes_pod_logs`: Only line in the logs: 'building monthly report: loading 200MB of rows'. The previous instance's logs are gone, so this is the latest instance.
- `kubernetes_describe_deployment`: reports has a single revision 1 (ReplicaSet reports-55b4fffc66) created 2m ago with a 48Mi memory limit; 0/1 ready, Available=False

**Recommendations**
1. Raise the reports memory limit and request to cover the real peak. It loads about 200MB of rows, so start with something like 256Mi request and 320Mi limit (observed peak plus 25%, as the oom-killed runbook says). Change the deployment manifest and roll it out.
2. After the rollout, confirm the pod stays Running with no new OOMKilled restarts. If Prometheus is available, check container_memory_working_set_bytes to get the limit right.
3. Longer term, consider streaming or batching the report rows instead of loading all 200MB into memory at once.
4. Don't restart the pod: a restart won't help while the limit stays at 48Mi.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 100}
4. `incidents_search` {"keywords": "reports crashloop"}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
