## reports-55b4fffc66-hmq7f in demo (prod-eu) keeps getting OOMKilled (exit 137, 3 restarts). It loads about 200MB of rows for the monthly report, but its memory limit is only 48Mi.

**Root cause** (high confidence, `resource_limits`): The memory limit doesn't fit what the job does. The app container (python:3.12-alpine) has a 48Mi limit and a 32Mi request. On startup it logs 'building monthly report: loading 200MB of rows', so it goes over the limit and the kernel kills it every time (current and last state are both OOMKilled, exit code 137). Nothing changed to cause this: the reports deployment was created at revision 1 about 2 minutes ago and has never had a working revision. It likely never had enough memory. The only other recent change is checkout revision 2, which removed DATABASE_URL. That's a separate workload and nothing shows reports depending on it. I had no memory usage metrics, so the 200MB figure comes from the app's own log line, not from measurement.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_describe_pod`: Container app: limits memory 48Mi, requests 32Mi. State terminated OOMKilled exit 137, last_state OOMKilled exit 137, 3 restarts, BackOff events.
- `kubernetes_pod_logs`: Latest instance log (previous logs gone): 'building monthly report: loading 200MB of rows'.
- `kubernetes_recent_changes`: reports was created at revision 1 about 2m ago with no later rollout. The only rollout was checkout rev 2 (DATABASE_URL removed), a different workload.
- `runbooks_runbook_for_alert`: The oom-killed runbook says to raise the limit and request to observed peak plus 25%, or fix the leak. Restarting only buys time.

**Recommendations**
1. Raise the reports memory limit to fit the working set: about 200MB of rows plus Python overhead. Start around 320Mi and set the request close to it, then fine-tune from observed peak plus 25%.
2. After the change, confirm the pod stays Running and reports finish. If Prometheus is available, watch container_memory_working_set_bytes for the pod.
3. Longer term, have the report stream or page through rows in batches so memory doesn't grow with data volume.
4. Don't restart the pod: with a 48Mi limit it will just be OOMKilled again.
5. Look at the checkout rev 2 rollout (DATABASE_URL removed) separately. It isn't related to this alert, but it could break checkout.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
3. `kubernetes_pod_logs` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true}
4. `kubernetes_recent_changes` {"cluster": "prod-eu"}
5. `incidents_search` {"keywords": "reports crashloop"}
