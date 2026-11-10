## The reports pod in prod-eu is crash looping because it is OOMKilled (exit 137). The memory limit is 48Mi, but the app logs show it loading about 200MB of rows. No rollout is involved.

**Root cause** (high confidence, `resource_limits`): The app container has a memory limit of 48Mi (request 32Mi). On startup it logs "building monthly report: loading 200MB of rows", so it needs far more memory than the limit allows. The kernel OOM-kills it each time (exit 137, 3 restarts). Revision 1 is the only revision and has never run successfully, so this is a limit that was too low from the start rather than a regression. I did not check Prometheus memory usage, so the exact peak is unmeasured.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: app last terminated OOMKilled, exit code 137, 3 restarts, ready 0/1
- `kubernetes_describe_pod`: app container memory limit 48Mi, request 32Mi; BackOff restarting failed container; no env or probes configured
- `kubernetes_pod_logs`: Log line: "building monthly report: loading 200MB of rows", far above the 48Mi limit
- `kubernetes_recent_changes`: reports has only revision 1 (created), with no later rollout. The checkout rollout and the frontend image problem are separate.
- `runbooks_runbook_for_alert`: The oom-killed runbook applies: if memory is flat just under the limit, the limit is too small. The fix is to raise the limit to the observed peak plus 25%, or to fix the memory use.

**Recommendations**
1. Raise the reports memory limit and request. The workload loads about 200MB, so start around 256-384Mi and adjust to the observed peak plus 25%.
2. Check container_memory_working_set_bytes in Prometheus for the reports pod to find the real peak.
3. Consider changing the job to stream or paginate rows instead of loading 200MB at once.
4. Don't just restart the pod. It will be OOMKilled again.
5. Handle the checkout (DATABASE_URL env removed in revision 2) and frontend (non-existent nginx tag) problems separately. They are unrelated to this alert.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "prod-eu", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "prod-eu"}
4. `incidents_search` {"keywords": "reports"}
5. `kubernetes_describe_pod` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
6. `kubernetes_pod_logs` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 30}
