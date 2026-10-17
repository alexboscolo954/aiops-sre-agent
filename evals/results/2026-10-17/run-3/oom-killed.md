## Pod reports-7cc9978bbf-sq7r7 is crash looping because it is OOMKilled (exit 137). Its memory limit is 48Mi, but the job loads about 200MB of rows.

**Root cause** (high confidence, `resource_limits`): The reports container has a 48Mi memory limit (32Mi request). On startup it logs 'building monthly report: loading 200MB of rows', so its working set far exceeds the limit and the kernel OOM-kills it on every start. There is only one revision (rev 1), so this is not a rollout regression. The limit is too low for the workload, and it could also be a memory-hungry code path that loads everything at once.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-7cc9978bbf-sq7r7

**Evidence**
- `kubernetes_list_pods`: reports-7cc9978bbf-sq7r7 is 0/1 ready with 2 restarts, last terminated OOMKilled, exit code 137
- `kubernetes_describe_pod`: Container app has limits.memory=48Mi and requests.memory=32Mi. Its state is terminated OOMKilled, with a BackOff warning event.
- `kubernetes_pod_logs`: Latest log line: 'building monthly report: loading 200MB of rows', which is far more than the 48Mi limit
- `kubernetes_describe_deployment`: Only revision 1 exists, with the same 48Mi limit. There is no earlier working revision, so it is not a bad rollout.

**Recommendations**
1. Raise the reports memory limit and request to cover the observed peak plus about 25%. The 200MB load implies at least ~256Mi; confirm the real peak with container_memory_working_set_bytes in Prometheus.
2. If the memory footprint is unintended, change the report job to stream or paginate rows instead of loading 200MB at once.
3. Apply the change through the deployment manifest and watch that the pod becomes Ready and stops restarting. A plain restart will not help.
4. Note that the other demo pods are separate problems: checkout has a crash (exit 1) and frontend has an ErrImagePull on nginx:1.99.99-does-not-exist. Triage them separately.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_pod`
4. `kubernetes_pod_logs`
5. `kubernetes_describe_deployment`
