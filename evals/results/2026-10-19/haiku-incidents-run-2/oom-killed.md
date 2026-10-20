## The reports pod is crash looping because its app container is OOMKilled (exit 137) at a 48Mi memory limit. Its log shows it loading about 200MB of rows to build a monthly report. This is a single revision created 2 minutes ago, so no rollout regression is involved: the limit is too small for the workload's actual work.

**Root cause** (medium confidence, `resource_limits`): The reports container has a memory limit of 48Mi (request 32Mi) and is OOMKilled on every start (last state OOMKilled, exit 137, restarts 3). The previous instance's log ends with 'building monthly report: loading 200MB of rows', so the job needs far more than 48Mi. Only one revision exists (reports-55b4fffc66, created 2m ago), so this is not a bad rollout. The deciding fact is the 48Mi limit against a job that loads roughly 200MB. Memory usage in Prometheus was not queried, so the exact peak is unconfirmed.
**Severity:** high  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_describe_pod`: Container app (python:3.12-alpine): limits memory 48Mi, requests memory 32Mi; state and last_state both terminated OOMKilled, exit_code 137; restarts 3; Ready False (ContainersNotReady).
- `kubernetes_pod_logs`: Previous instance logs were gone; latest instance shows 'building monthly report: loading 200MB of rows' before the kill.
- `kubernetes_describe_deployment`: Deployment reports has 1 desired and 0 ready replicas; Available False (MinimumReplicasUnavailable); single rollout_history revision 1 with memory limit 48Mi, so there is no earlier revision to roll back to.
- `kubernetes_recent_changes`: Only reports revision 1 'created' 2m ago with no diff. No rollout of reports in the window.
- `runbooks_runbook_for_alert`: KubePodCrashLooping runbook: OOMKilled points to the oom-killed runbook. Fix is to raise the limit to observed peak plus 25%, or fix a leak.
- `incidents_search`: No past incident in the last 90 days matches reports OOMKilled crashloop.

**Recommendations**
1. Raise the reports container memory limit well above the observed ~200MB peak (for example 256Mi or more) and set the request to match, through the owning manifest or Helm values. Confirm the peak first with max by (pod) (container_memory_working_set_bytes{namespace="demo",container="app"}) over a run if Prometheus is available.
2. Or change the job to stream rows instead of loading all 200MB into memory, if that is feasible.
3. Do not restart the pod as a fix; it will be OOM killed again on the next run.
4. Outside this alert: the checkout deployment rolled out revision 2 about 48s ago, removing the DATABASE_URL env var from app. It is unrelated to reports as far as the evidence shows, but it may need its own triage.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "container": "app", "previous": true, "tail_lines": 40}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
6. `incidents_search` {"keywords": "reports OOMKilled crashloop", "days": 90, "limit": 5}
