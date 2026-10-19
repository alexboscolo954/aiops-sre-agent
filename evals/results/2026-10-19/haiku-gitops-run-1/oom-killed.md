## Pod reports-55b4fffc66-hmq7f is crash looping because its app container is OOMKilled (exit 137) under a 48Mi memory limit while loading a 200MB batch of rows. The reports deployment has only revision 1 and no recent rollout, so this looks like a limit set too low for the workload rather than a regression. A separate checkout rollout (revision 2, DATABASE_URL removed) is also crash looping in the same namespace and is not the alerted pod.

**Root cause** (medium confidence, `resource_limits`): The reports container's memory limit (48Mi) is far below what the job needs. The log shows it loading 200MB of rows, and the container is OOMKilled on each start. The limit was never raised for this data volume. The cause is inferred from the limit and the log line, not from a memory graph.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f, demo/Deployment/checkout

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: Running, 0/1 ready, restarts=3, last_terminated OOMKilled exit 137
- `kubernetes_describe_pod`: Container app (image python:3.12-alpine): requests memory 32Mi, limits memory 48Mi, state OOMKilled exit 137, restarts 3; no env or probes configured
- `kubernetes_pod_logs (previous=true)`: Last log line before the kill: "building monthly report: loading 200MB of rows"
- `kubernetes_recent_changes`: reports has only revision 1 (created about 2m ago); no rollout that could explain the change
- `kubernetes_list_pods`: Related: checkout-869fc5bcc6-db5ps is in Error (exit 1), restarts=3, 0/1 ready; the checkout rollout to revision 2 removed env DATABASE_URL from container app

**Recommendations**
1. Confirm the memory need with Prometheus (container_memory_working_set_bytes for pod reports-55b4fffc66-hmq7f) or by testing a larger limit. Then raise the reports memory limit and request to observed peak plus about 25%. The 48Mi limit is far too small for loading 200MB of rows, so a limit well above 200Mi is likely needed. If usage keeps growing past that, investigate a leak in the reports code.
2. Make the change through the owning team's GitOps or Helm config, not a live edit, and roll it out.
3. Separately, checkout revision 2 removed DATABASE_URL from the app container, which is a bad_rollout. Roll checkout back to revision 1 or restore DATABASE_URL. Check the checkout logs (previous=true) to confirm the startup error before acting.
4. Do not restart the pods as a fix. A restart does not change the memory limit or the missing config.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_recent_changes`
4. `kubernetes_describe_pod`
5. `kubernetes_pod_logs`
