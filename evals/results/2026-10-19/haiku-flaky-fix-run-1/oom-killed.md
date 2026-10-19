## The reports pod is OOMKilled on every start because its memory limit is 48Mi, and its log shows it loading 200MB of rows. No rollout touched reports (it has only revision 1, created about 2 minutes ago), so the limit is the likely cause, not a regression. Two other workloads in the demo namespace are also broken (checkout crash loop and frontend ErrImagePull) but are outside this alert.

**Root cause** (medium confidence, `resource_limits`): The reports container (python:3.12-alpine) has a memory limit of 48Mi and a request of 32Mi. Its last state is OOMKilled with exit code 137 on 3 restarts. The only log line from the run before the kill is 'building monthly report: loading 200MB of rows', so the working set needed to load that data is far above 48Mi. The limit is too small for a healthy workload. The deployment has only revision 1, created about 2 minutes ago, so no recent change caused this. Prometheus was not available to confirm the exact peak memory.
**Severity:** high  ·  **Affected:** demo/Pod/reports-55b4fffc66-hmq7f, demo/Deployment/reports

**Evidence**
- `runbooks_runbook_for_alert`: KubePodCrashLooping maps to the pod-crashlooping and oom-killed runbooks; OOMKilled with exit 137 points to the oom-killed runbook.
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: 0/1 ready, 3 restarts, last_terminated OOMKilled, exit code 137.
- `kubernetes_describe_pod`: Container app: image python:3.12-alpine, requests memory 32Mi, limits memory 48Mi, state and last_state both OOMKilled exit 137, restarts 3.
- `kubernetes_pod_logs`: Previous instance logs are gone; the latest instance shows 'building monthly report: loading 200MB of rows'.
- `kubernetes_recent_changes`: reports revision 1 'created' 2m ago with no diff. No reports rollout exists, so no recent change to blame.
- `runbooks_read_runbook`: oom-killed runbook: a flat line just under the limit means the limit is too small. Fix by raising the limit to observed peak plus 25%, or fix the leak.

**Recommendations**
1. Measure the real peak memory of the reports job (Prometheus container_memory_working_set_bytes for the pod, or a local test of loading the 200MB dataset). Then raise the memory limit and request to peak plus 25%. 48Mi is far too low for a 200MB load, so expect a much larger value, e.g. a few hundred MiB.
2. Alternatively, change the report job to stream or chunk the rows so it needs less memory, and keep the limit as is.
3. Separately, the checkout deployment (revision 2, 48s ago) removed the DATABASE_URL env var from container app and is crash looping with exit 1. Roll back checkout to revision 1 or restore DATABASE_URL.
4. Separately, frontend-6f6b4986b9-hxdf2 is in ErrImagePull because the image tag nginx:1.99.99-does-not-exist does not exist. Correct the image tag.
5. Verify the reports fix: the pod should reach 1/1 Ready with no new OOMKilled restarts.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_recent_changes`
4. `kubernetes_describe_pod`
5. `runbooks_read_runbook`
6. `kubernetes_pod_logs`
