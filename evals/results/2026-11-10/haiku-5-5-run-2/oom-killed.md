## Pod reports-55b4fffc66-hmq7f (demo) is crash looping with OOMKilled (exit 137) at a 48Mi memory limit. The script loads about 200MB of rows, so the limit is far too small. The reports deployment has a single revision, created 2m ago, so this is a limit that was never sized for the workload, not a regression from a rollout.

**Root cause** (medium confidence, `resource_limits`): The container's memory limit is 48Mi (request 32Mi). The app log says "building monthly report: loading 200MB of rows" and the container is OOMKilled (exit 137) on every start (3 restarts, last terminated OOMKilled). A 200MB working set cannot fit under a 48Mi limit, so the limit is too low for a healthy workload. This is the only revision of the deployment, so no recent rollout caused it. Memory usage was not checked in Prometheus; the conclusion rests on the limit versus the logged data size.
**Severity:** high  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: Running, 0/1 ready, restarts 3, last_terminated app OOMKilled exit 137
- `kubernetes_describe_pod`: container app: limits memory 48Mi, requests memory 32Mi; last_state OOMKilled exit 137; events show BackOff restarting failed container app
- `kubernetes_pod_logs`: previous instance logs gone; latest instance logs: 'building monthly report: loading 200MB of rows'
- `kubernetes_describe_deployment`: reports has one rollout revision (revision 1, created 2m ago), image python:3.12-alpine, no env changes; Available=False MinimumReplicasUnavailable
- `kubernetes_recent_changes`: reports revision 1 'created' 2m ago with no diff; no other rollout relates to reports
- `runbooks_read_runbook`: oom-killed runbook: OOMKilled exit 137 means raise limit to observed peak plus 25%, or fix the leak

**Recommendations**
1. Confirm peak memory with Prometheus: max by (pod) (container_memory_working_set_bytes{namespace="demo", pod=~"reports-.*", container="app"}) over the last hour. If the data really is about 200MB, the peak is above 200MB.
2. Raise the memory limit (and request) of the reports deployment's app container to the observed peak plus 25%. At least 256Mi is likely needed, based on the 200MB log line. Change it through the owning config (Helm/GitOps) so it is not reverted.
3. Check whether the script can stream rows instead of loading all 200MB at once. That would reduce the memory needed.
4. Separately, the same namespace has other problems that this alert does not cover: checkout (DATABASE_URL removed in revision 2) and frontend (image nginx:1.99.99-does-not-exist). Those need their own triage.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true}
7. `incidents_search` {"keywords": "reports OOMKilled demo"}
8. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": "app=reports"}
9. `runbooks_read_runbook` {"name": "oom-killed"}
10. `TriageReport` {"summary": "Pod reports-55b4fffc66-hmq7f (demo) is crash looping with OOMKilled (exit 137) at a 48Mi memory limit. The script loads about 200MB of rows, so the limit is far too small. The reports deployment has a single revision, created 2m ago, so this is a limit that was never sized for the workl
11. `TriageReport` {"summary": "Pod reports-55b4fffc66-hmq7f (demo) is crash looping with OOMKilled (exit 137) at a 48Mi memory limit. The script loads about 200MB of rows, so the limit is far too small. The reports deployment has a single revision, created 2m ago, so this is a limit that was never sized for the workl
