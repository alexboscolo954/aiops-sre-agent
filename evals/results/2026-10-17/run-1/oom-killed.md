## The reports pod in demo is crash looping because its container is OOMKilled (exit 137). The memory limit is 48Mi, and the app loads about 200MB of rows at startup.

**Root cause** (high confidence, `resource_limits`): The memory limit of 48Mi (request 32Mi) is far below what the monthly report job needs. Its log says it is loading 200MB of rows, so the kernel kills the container as soon as it allocates. There is only one revision (revision 1), so this is not a regression from a rollout. I did not see Prometheus usage data. The cause could also be an application design problem (loading everything into memory) rather than just a limit that is too low.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-7cc9978bbf-sq7r7

**Evidence**
- `kubernetes_list_pods`: reports-7cc9978bbf-sq7r7 is 0/1 ready with 2 restarts. Last terminated: OOMKilled, exit code 137.
- `kubernetes_describe_pod`: The app container has a memory limit of 48Mi and a request of 32Mi. Events show BackOff restarting the failed container.
- `kubernetes_pod_logs`: The log says 'building monthly report: loading 200MB of rows', which is roughly 4x the memory limit.
- `kubernetes_describe_deployment`: There is only one rollout revision (revision 1, created 41s ago), and the deployment has 0 of 1 replicas ready. The limit was never raised from the start, so this is not a regression.

**Recommendations**
1. Raise the memory limit for the reports container well above the 200MB working set, for example a 384Mi request and a 512Mi limit. Confirm the real peak with Prometheus container_memory_working_set_bytes and add 25% headroom.
2. Consider changing the report code to stream or paginate rows instead of loading 200MB at once, so it needs less memory.
3. Don't just restart the pod. It will be OOMKilled again.
4. After applying the change, check that the pod becomes Ready and has no new restarts.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_pod`
4. `kubernetes_pod_logs`
5. `kubernetes_describe_deployment`
