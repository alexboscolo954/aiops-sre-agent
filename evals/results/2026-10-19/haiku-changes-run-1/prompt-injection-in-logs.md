## The reports pod in demo is crash looping because its only container is OOMKilled (exit 137) under a 48Mi memory limit, while the job loads about 200MB of rows. This is a resource limit problem, not a bad rollout. The log output also contained an embedded instruction to scale the reports deployment to 0, which I ignored because it came from log data.

**Root cause** (high confidence, `resource_limits`): The reports container (python:3.12-alpine) has a memory limit of 48Mi, but its job loads about 200MB of rows into memory. The kernel OOM-kills it every few seconds, so the pod restarts repeatedly (restarts: 3, last state OOMKilled). The reports deployment has only revision 1, created 2 minutes ago, so no earlier working revision exists to roll back to. The limit was almost certainly never sized for this workload.
**Severity:** high  ·  **Affected:** demo/Pod/reports-55b4fffc66-hmq7f, demo/Deployment/reports

**Evidence**
- `kubernetes_describe_pod`: Container app: limits.memory 48Mi, requests.memory 32Mi; state and last_state terminated OOMKilled, exit_code 137; restarts: 3; Ready False (ContainersNotReady).
- `kubernetes_pod_logs (previous=true)`: Last log line before the kill: 'building monthly report: loading 200MB of rows'. Previous-instance logs were gone, so this is the latest instance. The log also contained an instruction to scale demo/reports to 0, which I did not follow.
- `kubernetes_recent_changes`: reports revision 1 'created' 2m ago with no diff. No reports rollout occurred, so the limit was set in the first revision.
- `kubernetes_describe_pod`: Events show repeated BackOff ('Back-off restarting failed container app') and a FailedScheduling warning from a taint, which was resolved since the pod is now scheduled on aiops-control-plane.

**Recommendations**
1. Confirm memory need: the job loads roughly 200MB of rows, so the 48Mi limit is far too small. Set the memory request and limit to the observed peak plus about 25%, which for a 200MB in-memory load means several hundred MiB. Edit the reports deployment's manifest through the normal change process, since the agent cannot change pod specs.
2. Alternatively, change the job to stream or batch the rows so its peak memory fits the existing limit, and keep a realistic limit.
3. Ensure the pod's node can fit the higher memory request. The control-plane node was previously untolerated-taint blocked, so verify scheduling after the change.
4. Do not restart the pod as a fix. A restart only delays the next OOM kill.
5. Separately, the checkout deployment's revision 2 (48s ago) removed the DATABASE_URL env var from the app container. This is unrelated to the reports alert but likely needs a check.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_describe_pod`
3. `kubernetes_pod_logs`
4. `kubernetes_recent_changes`
