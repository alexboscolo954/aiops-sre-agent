## Pod reports-55b4fffc66-hmq7f is crash looping because its container is OOMKilled (exit 137) under a 48Mi memory limit. The app loads about 200MB of rows at startup, so the limit is far below what it needs. The reports deployment is on its first revision, so no rollout caused this.

**Root cause** (medium confidence, `resource_limits`): The container 'app' (python:3.12-alpine) has memory limit 48Mi and request 32Mi. Its last log line before the kill is 'building monthly report: loading 200MB of rows', so the working set exceeds 48Mi as soon as it loads data. The kernel OOM-kills it (exit 137, restarts: 3). The deployment has only revision 1, created about 2 minutes before the alert, so this is not a regression from a new revision. The checkout rollout (DATABASE_URL removed) is a different workload and shows no dependency on reports.
**Severity:** high  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_describe_pod`: Container app: limits memory 48Mi, requests memory 32Mi; state terminated OOMKilled exit_code 137; last_state OOMKilled; restarts 3; Ready False (ContainersNotReady).
- `kubernetes_pod_logs`: Previous instance logs are gone; latest instance shows only 'building monthly report: loading 200MB of rows' before the kill.
- `kubernetes_describe_pod`: Events show BackOff restarting failed container app, and the image python:3.12-alpine was already present on the node. The image pull was slow (1m21s) but succeeded, so this is not an image problem.
- `kubernetes_recent_changes`: reports revision 1 was 'created' 2m ago, with no later revision. The only rollout in the window is checkout revision 2 (env DATABASE_URL removed), a different workload.

**Recommendations**
1. Confirm peak memory with Prometheus: max by (pod) (container_memory_working_set_bytes{namespace="demo",pod=~"reports-.*",container!=""}). A flat line near 48Mi confirms the limit is too low; steady growth would point to a leak instead.
2. Raise the reports container memory limit (and request) to the observed peak plus about 25%. At least 256Mi is a reasonable starting point for loading 200MB of rows, pending the measurement. Alternatively, change the report job to stream rows instead of loading them all at once.
3. Scheduling note: the pod landed on squero-control-plane despite an untolerated taint. Check why it was scheduled there before relying on that node for this workload.
4. Do not restart the pod as a fix. It will crash again until the limit or the code changes.

Runbook: `oom-killed`

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
2. `kubernetes_pod_logs` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "container": null, "tail_lines": 100, "previous": true}
3. `kubernetes_recent_changes` {"cluster": "prod-eu", "since_minutes": 360}
4. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
5. `incidents_search` {"keywords": "reports OOMKilled memory", "days": 90, "limit": 5}
