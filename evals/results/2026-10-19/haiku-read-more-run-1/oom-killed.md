## The alerting pod reports-55b4fffc66-hmq7f is crash looping because its container is OOMKilled (exit 137) under a 48Mi memory limit. The reports deployment has only one revision, so no rollout caused this. Separately, the checkout deployment's rollout removed DATABASE_URL and is also crash looping, and frontend is stuck in ErrImagePull; both are outside this alert but need attention.

**Root cause** (medium confidence, `resource_limits`): The reports container (python:3.12-alpine) has a memory limit of 48Mi (request 32Mi) and is killed with OOMKilled, exit 137, on every start: 3 restarts, last terminated 25-30s before the check. The deployment has only revision 1 (created 2m ago), so this is not a new revision. Memory usage metrics were not available, so I cannot tell whether the limit is simply too small for a healthy workload or the process leaks memory. The 48Mi limit is very tight for a Python process, which points to the limit being too low.
**Severity:** high  ·  **Affected:** demo/Pod/reports-55b4fffc66-hmq7f, demo/Deployment/reports

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: Running, 0/1 ready, restarts=3, last_terminated app=OOMKilled exit_code 137.
- `kubernetes_describe_pod`: Container app: image python:3.12-alpine, requests memory 32Mi, limits memory 48Mi; state and last_state both OOMKilled exit 137; events show BackOff restarting failed container app.
- `kubernetes_describe_deployment`: reports has a single rollout_history revision (revision 1, created 2m ago) with the same image and no env changes; Available=False, MinimumReplicasUnavailable.
- `kubernetes_recent_changes`: The only reports change is revision 1 'created' at 2m; no rollout happened shortly before the alert.
- `runbooks_runbook_for_alert`: The oom-killed runbook says a flat memory line just under the limit means the limit is too small, and steady growth means a leak. Following it, raising the limit is the first step.
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago removed env var DATABASE_URL from container app. This is a separate workload, not the alerting pod.
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps: 0/1 ready, restarts=3, last_terminated Error exit_code 1. frontend-6f6b4986b9-hxdf2: Pending, ErrImagePull for nginx:1.99.99-does-not-exist.

**Recommendations**
1. Check memory growth for reports-55b4fffc66-hmq7f with Prometheus (container_memory_working_set_bytes for namespace demo) or previous logs, to tell a too-small limit from a leak.
2. If usage is flat near the limit, raise reports' memory limit and request (for example to 96Mi or more, based on observed peak plus 25%). Get human approval before changing the deployment.
3. If usage grows steadily, treat it as an application memory leak and escalate to the owning team; a limit increase only delays the next kill.
4. Separately, roll back or fix checkout: revision 2 removed DATABASE_URL from the app container. Restore the env var or its secret source, then check checkout's logs with previous=true.
5. Separately, fix the frontend image tag (nginx:1.99.99-does-not-exist) to a tag that exists.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_recent_changes`
4. `kubernetes_describe_pod`
5. `kubernetes_describe_deployment`
