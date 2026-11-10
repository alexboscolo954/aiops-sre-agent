## Pod reports-55b4fffc66-hmq7f (demo, prod-eu) is crash looping with OOMKilled (exit 137) on a 48Mi memory limit. The app is a python:3.12-alpine container that loads 200MB of rows for a monthly report, so the limit is far below what the workload needs. The deployment has one revision, created 2m ago, so this looks like a configuration/limit problem in the original deployment rather than a regression.

**Root cause** (high confidence, `resource_limits`): The container's memory limit is 48Mi (request 32Mi), but the job logs "building monthly report: loading 200MB of rows", so the process needs far more than 48Mi. The kernel OOM-kills it (exit 137, last_state OOMKilled, 3 restarts). The deployment has only revision 1 (created 2m ago), so no rollout introduced this. The limit was too small from the start. Memory usage metrics were not checked, so the exact peak is unknown.
**Severity:** high  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f container app: limits.memory 48Mi, requests.memory 32Mi; last_state OOMKilled exit_code 137; restarts 3
- `kubernetes_pod_logs`: Latest instance log: 'building monthly report: loading 200MB of rows' before being killed
- `kubernetes_describe_deployment`: reports has a single revision (1, created 2m ago); memory limit 48Mi unchanged in that revision
- `kubernetes_recent_changes`: reports revision 1 'created' 2m ago; no later rollout for reports
- `runbooks_runbook_for_alert`: KubePodCrashLooping runbook: OOMKilled (exit 137) points to the oom-killed runbook; fix is to raise the limit to observed peak +25% or fix the leak

**Recommendations**
1. Raise the memory limit and request for demo/reports well above the 200MB the job loads (for example a limit of 256Mi or more, with the request raised to match), then roll it out. Confirm the value with the report owner, since the peak usage was not measured.
2. Alternatively, change the job to stream rows instead of loading all 200MB into memory, which fixes the root cause.
3. Query container_memory_working_set_bytes for pod reports-55b4fffc66-hmq7f to confirm the peak before choosing the new limit.
4. Separately, the frontend deployment is stuck in ErrImagePull on the nonexistent tag nginx:1.99.99-does-not-exist, and checkout revision 2 removed DATABASE_URL and is crashing with exit code 1. Those are outside this alert but need their own triage.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
3. `kubernetes_pod_logs` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true}
4. `kubernetes_recent_changes` {"cluster": "prod-eu"}
5. `kubernetes_describe_deployment` {"cluster": "prod-eu", "namespace": "demo", "name": "reports"}
6. `incidents_search` {"keywords": "reports OOMKilled crashloop demo"}
7. `kubernetes_list_pods` {"cluster": "prod-eu", "namespace": "demo", "label_selector": "app=reports"}
8. `runbooks_read_runbook` {"name": "oom-killed"}
9. `TriageReport` {"summary": "Pod reports-55b4fffc66-hmq7f (demo, prod-eu) is crash looping with OOMKilled (exit 137) on a 48Mi memory limit. The app is a python:3.12-alpine container that loads 200MB of rows for a monthly report, so the limit is far below what the workload needs. The deployment has one revision, cr
10. `TriageReport` {"summary": "Pod reports-55b4fffc66-hmq7f (demo, prod-eu) is crash looping with OOMKilled (exit 137) on a 48Mi memory limit. The app is a python:3.12-alpine container that loads 200MB of rows for a monthly report, so the limit is far below what the workload needs. The deployment has one revision, cr
