## reports-55b4fffc66-hmq7f is crash looping. It is OOMKilled (exit 137) at its 48Mi memory limit while loading 200MB of rows into memory. The pod has no env vars set.

**Root cause** (medium confidence, `bad_config`): The reports container has a 48Mi memory limit and no env vars set. Its log says "building monthly report: loading 200MB of rows", so it loads the whole dataset at once, which is about 4x the limit, and the kernel kills it every run. A past incident (5b0e2c4e) on this workload found the same pattern: the job reads its batch size from REPORTS_BATCH_SIZE, and unset it loads the whole table. Setting REPORTS_BATCH_SIZE=1000 fixed it then. I have not confirmed from the code that the env var is still the setting that controls batching. The deployment has only revision 1, so no rollout caused this. The missing config has been there since creation.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f has 3 restarts and last terminated as OOMKilled with exit code 137; it is 0/1 ready.
- `kubernetes_describe_pod`: Container app has a 48Mi memory limit (request 32Mi), env is empty ([]), and there are no probes. The BackOff warning is present and the image pulled fine.
- `kubernetes_pod_logs`: The only log line is 'building monthly report: loading 200MB of rows', which is far more than the 48Mi limit.
- `kubernetes_recent_changes`: The reports deployment only has revision 1 (created about 2m ago), so no rollout is to blame. The checkout and frontend changes are unrelated.
- `incidents_search`: A past incident (5b0e2c4e) on reports had the same OOMKill at 48Mi. The cause was REPORTS_BATCH_SIZE being unset, and setting it to 1000 fixed it. I used this as a lead only and did not read the full report.

**Recommendations**
1. Set REPORTS_BATCH_SIZE=1000 on the reports deployment's app container so rows stream in batches, then confirm the pod stays under the limit.
2. If it still gets OOMKilled, check actual memory use against the 48Mi limit and raise the limit and request to the observed peak plus 25%.
3. Raising the limit alone only buys time as the table grows (see the past incident). Consider adding REPORTS_BATCH_SIZE to the deployment manifest in git so it isn't lost.
4. Don't restart the pod: a restart doesn't fix a crash loop.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "reports"}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 30}
