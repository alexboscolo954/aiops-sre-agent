## The reports pod reports-55b4fffc66-hmq7f is crash looping because its app container is OOMKilled (exit 137) under a 48Mi memory limit while it loads a 200MB report. The reports deployment has only revision 1, so no rollout caused this. A separate checkout pod in the same namespace is also failing after a rollout that removed DATABASE_URL, which is not the alerting workload.

**Root cause** (medium confidence, `resource_limits`): The memory limit of 48Mi on the reports app container is far below what the workload needs. The last log line is 'building monthly report: loading 200MB of rows', and the container is OOMKilled each time it starts that load. This looks like a limit that is too small for a healthy job, not a new regression. I could not confirm steady memory growth or a leak because Prometheus was not available.
**Severity:** high  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f is Running 0/1 with 3 restarts; last_terminated app = OOMKilled, exit code 137.
- `kubernetes_describe_pod`: Container app (python:3.12-alpine) has requests memory 32Mi and limits memory 48Mi; state OOMKilled, exit 137, restarts 3. Events show BackOff restarting failed container app.
- `kubernetes_pod_logs`: Latest instance log: 'building monthly report: loading 200MB of rows'. The previous instance's logs were no longer available.
- `kubernetes_recent_changes`: reports has only revision 1 (created about 2m ago), with no rollout diff, so a bad rollout is ruled out.

**Recommendations**
1. Raise the reports app container memory limit well above the 200MB data load, for example 256Mi, and set the request to match. Confirm the figure against observed peak usage plus 25%, which needs Prometheus or a test run.
2. If the report code loads all 200MB into memory, change it to stream or chunk the rows so the job does not need the full dataset in RAM.
3. Check the reports pod after the change: the restart count should stop rising and the pod should reach 1/1 Ready.
4. Separately, roll back checkout to revision 1 or restore its DATABASE_URL env var. Revision 2 removed DATABASE_URL and checkout-869fc5bcc6-db5ps is in Error with exit code 1. This is a bad_rollout and is outside this alert's scope.
5. Separately, frontend-6f6b4986b9-hxdf2 is in ErrImagePull because its image tag nginx:1.99.99-does-not-exist does not exist. Fix the image tag.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_recent_changes`
4. `kubernetes_describe_pod`
5. `kubernetes_pod_logs`
