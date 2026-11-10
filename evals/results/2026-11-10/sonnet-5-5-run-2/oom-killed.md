## The reports pod is crash looping because its container is OOMKilled (exit 137). The memory limit is 48Mi, and the app loads about 200MB of rows at startup.

**Root cause** (high confidence, `resource_limits`): The reports container (python:3.12-alpine) has a memory limit of 48Mi and a request of 32Mi. Its log says "building monthly report: loading 200MB of rows", so it needs several times the limit and the kernel OOM-kills it each time. Revision 1 is the only revision and no rollout preceded the alert. The cause is the limit being too small, not a change.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: 3 restarts, last terminated OOMKilled, exit code 137, ready 0/1
- `kubernetes_describe_pod`: Container app has a memory limit of 48Mi and a request of 32Mi. State is OOMKilled with a BackOff warning event. No env vars, no probes.
- `kubernetes_pod_logs`: Log shows "building monthly report: loading 200MB of rows", well above the 48Mi limit. Previous-instance logs were gone, so this is from the latest instance.
- `kubernetes_recent_changes`: The reports deployment has only revision 1 (created), so there was no rollout to blame. The checkout rollout and the frontend image problem are separate.

**Recommendations**
1. Raise the reports container memory limit and request to cover the real peak. Loading 200MB needs roughly 256-512Mi. Confirm the peak with container_memory_working_set_bytes and add 25% headroom.
2. Better still, change the app to stream or paginate the rows instead of loading 200MB at once, so it fits in a small limit.
3. Don't just restart the pod. It will be OOMKilled again.
4. Separate issues in the demo namespace: checkout crashes after revision 2 removed the DATABASE_URL env var, and frontend has ErrImagePull on the nonexistent tag nginx:1.99.99-does-not-exist. Triage those separately.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "reports"}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 30}
