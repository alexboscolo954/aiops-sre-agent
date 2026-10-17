## The reports pod is crash looping because it is OOMKilled. Its memory limit is 48Mi, and the app tries to load about 200MB of rows into memory.

**Root cause** (high confidence, `resource_limits`): The reports container has a 48Mi memory limit and a 32Mi request. Its workload ("building monthly report: loading 200MB of rows") needs far more than that, so the kernel kills it with exit 137. The deployment has only one revision, so this is not a regression from a rollout. The limit is too low for the job, or the job should stream or paginate its data instead of loading it all.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-7cc9978bbf-sq7r7

**Evidence**
- `kubernetes_list_pods`: reports-7cc9978bbf-sq7r7 is 0/1 ready with 2 restarts. The last termination was OOMKilled, exit code 137.
- `kubernetes_describe_pod`: The app container has a memory limit of 48Mi and a request of 32Mi. There are no probes and no env vars. A BackOff warning event is present.
- `kubernetes_pod_logs`: The only log line is 'building monthly report: loading 200MB of rows'. The previous instance's logs were gone, so this is from the latest instance. 200MB is far above the 48Mi limit.
- `kubernetes_describe_deployment`: Only revision 1 exists, and it has the same 48Mi limit. There is no earlier working revision to roll back to.

**Recommendations**
1. Raise the memory limit and request on the reports deployment to at least the observed peak plus 25%. Loading 200MB of rows suggests a limit of roughly 256Mi or more. Confirm the actual peak with container_memory_working_set_bytes.
2. Or change the report job to stream or paginate rows instead of loading 200MB at once, so it fits in a small limit.
3. Do not just restart the pod. Restarting does not fix an OOM crash loop.
4. After the change, check that the pod stays Running with no new OOMKilled terminations.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_pod`
4. `kubernetes_pod_logs`
5. `kubernetes_describe_deployment`
