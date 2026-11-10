## The reports pod is crash looping because it is OOMKilled (exit 137) at its 48Mi memory limit. The app loads about 200MB of rows at startup and the pod has no env vars set.

**Root cause** (medium confidence, `bad_config`): The container has a 48Mi memory limit (32Mi request) and no env vars. The log says "building monthly report: loading 200MB of rows", so the job loads the whole table into memory, which is far more than 48Mi, and the kernel OOM-kills it on every start. A past incident on this workload (5b0e2c4e) found the same pattern. Its cause was REPORTS_BATCH_SIZE being unset, and setting REPORTS_BATCH_SIZE=1000 fixed it. I did not see the app code, so the link to that variable is inferred from the past report and the empty env list. Revision 1 of reports was never changed, so this is not a bad rollout.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: 3 restarts, last terminated OOMKilled, exit code 137, ready 0/1
- `kubernetes_describe_pod`: Container app has a memory limit of 48Mi, a request of 32Mi and an empty env list. There are BackOff warning events and no probes.
- `kubernetes_pod_logs`: Latest instance logs (previous instance's logs were gone): "building monthly report: loading 200MB of rows"
- `kubernetes_recent_changes`: reports has only revision 1 (created), so there was no recent rollout. The only rollout was checkout revision 2, which removed DATABASE_URL and is a separate problem.
- `incidents_search`: Past incident 5b0e2c4e-9a51-4d1e-8f3a-2f6c7d1e0a93: reports was OOMKilled at its 48Mi limit because REPORTS_BATCH_SIZE was unset, and setting it to 1000 fixed it. I did not open the full report with incidents_read.

**Recommendations**
1. Set REPORTS_BATCH_SIZE=1000 on the reports deployment so rows are streamed instead of loaded all at once. The earlier incident kept the job under 40Mi this way.
2. Do not rely on only raising the memory limit. The past report says a raised limit stopped working once the table grew.
3. After the change, confirm the pod stays Running and has no new OOMKilled restarts.
4. Do not restart the pod, because that will not fix a crash loop.
5. Separately, the checkout alert is a different problem. Its revision 2 removed DATABASE_URL, so that rollout should be rolled back or the variable restored. The frontend pod is also failing because its image tag nginx:1.99.99-does-not-exist does not exist.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "reports"}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 30}
