## The reports pod is crash looping because its app container is OOMKilled (exit 137) under a 48Mi memory limit. The app logs say it is loading 200MB of rows, so the limit is far too small for the workload. The reports deployment has only revision 1, created 2 minutes ago, so this is not a bad rollout.

**Root cause** (medium confidence, `resource_limits`): The reports container has a memory limit of 48Mi (request 32Mi), but its last log line before the kill is "building monthly report: loading 200MB of rows". The kernel OOM-kills it every few seconds (last_state and state both OOMKilled, exit 137, restarts 3). The deployment has one revision (revision 1, created 2m ago, image python:3.12-alpine, no env changes), so no new revision caused this. The checkout rollout (revision 2, which removed DATABASE_URL) is a different workload and is not shown to be a dependency of reports. The 200MB figure comes from an application log line, not a memory metric, so the exact peak is unmeasured.
**Severity:** high  ·  **Affected:** demo/Pod/reports-55b4fffc66-hmq7f, demo/Deployment/reports

**Evidence**
- `kubernetes_describe_pod`: Container app in reports-55b4fffc66-hmq7f: limits memory 48Mi, requests memory 32Mi; state and last_state terminated OOMKilled, exit_code 137; restarts 3.
- `kubernetes_pod_logs`: Previous-instance logs were gone; latest instance log shows "building monthly report: loading 200MB of rows" before the container exits.
- `kubernetes_describe_deployment`: reports has one rollout revision (revision 1, created 2m ago, image python:3.12-alpine, no env). Deployment Available=False, MinimumReplicasUnavailable, replicas ready 0 of 1.
- `kubernetes_recent_changes`: Only changes were reports revision 1 created (2m) and checkout revision 2 rollout (48s, env_removed DATABASE_URL). No reports rollout preceded the crash.
- `kubernetes_describe_pod`: Events show a FailedScheduling taint warning and an image pull that took 1m21s; the image is now present, and the pod is running on squero-control-plane.

**Recommendations**
1. Raise the reports container memory limit well above the observed peak. A 200MB load needs roughly 256Mi or more (peak plus about 25%), and set the request to match. Confirm the peak with container_memory_working_set_bytes for demo/reports if Prometheus is available.
2. Alternatively, change the report job to stream rows instead of loading 200MB at once, which keeps the 48Mi limit viable.
3. Do not restart the pod to fix this; the crash loop will recur at the same limit.
4. Separately, check whether checkout revision 2 (which removed DATABASE_URL) is broken. It is not the cause of the reports crash, but it needs its own triage.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "container": "app", "tail_lines": 50, "previous": true}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
6. `incidents_search` {"keywords": "reports OOMKilled demo", "days": 90, "limit": 5}
