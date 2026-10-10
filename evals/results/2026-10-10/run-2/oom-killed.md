## The reports pod in demo is crash looping because it is OOMKilled. Its memory limit is 48Mi, and the job loads about 200MB of rows at startup.

**Root cause** (high confidence, `oom_killed`): The memory limit of 48Mi (request 32Mi) is far below what the monthly report job needs. The log says it is 'loading 200MB of rows', so the kernel kills the container with exit 137 and it restarts repeatedly. Only one revision exists, so this is not a regression from a rollout. The limit was probably too low from the start.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-7cc9978bbf-ddp5d

**Evidence**
- `kubernetes_list_pods`: reports-7cc9978bbf-ddp5d has 2 restarts, last terminated OOMKilled with exit code 137, and is 0/1 ready
- `kubernetes_pod_logs`: The log reads 'building monthly report: loading 200MB of rows'. Only the latest instance's logs were available, since the previous instance's logs were gone.
- `kubernetes_describe_pod`: Container app has a memory limit of 48Mi and a request of 32Mi. It has no probes and no env. Events show BackOff restarting the failed container.
- `kubernetes_describe_deployment`: There is only revision 1, created at about the same time as the pod, with the same 48Mi limit. There is no earlier healthy revision to roll back to.

**Recommended actions**
1. Raise the reports container memory limit and request well above the roughly 200MB working set. For example, request 256Mi and set the limit to 384-512Mi, then check real peak usage and size it as peak plus 25%.
2. Consider changing the report job to stream or paginate rows instead of loading 200MB at once, so it needs less memory.
3. After the change, confirm the pod stays Running with no new OOMKilled terminations. Restarting the pod will not fix this.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_pod_logs`
4. `kubernetes_describe_pod`
5. `kubernetes_describe_deployment`
