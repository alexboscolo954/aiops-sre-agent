## The reports pod is crash looping because it is OOMKilled (exit 137) at its 48Mi memory limit. Its startup log says it is loading 200MB of rows into memory.

**Root cause** (medium confidence, `bad_config`): The reports container has a 48Mi memory limit (request 32Mi) and no env vars set. Its log says it is "loading 200MB of rows", so the job loads the whole table into memory and the kernel kills it. A past incident on this workload (5b0e2c4e) had the same signature: REPORTS_BATCH_SIZE was unset, so the job did not stream rows. Setting REPORTS_BATCH_SIZE=1000 kept it under 40Mi. I did not read the incident in full, and I did not confirm the app's use of REPORTS_BATCH_SIZE in the current code. The match rests on the empty env, the 200MB log line and the limit. There was no rollout of reports: revision 1 only, created about 2m ago. The checkout and frontend failures are separate issues.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: 0/1 ready, 3 restarts, last terminated OOMKilled, exit code 137.
- `kubernetes_describe_pod`: Container app has memory limit 48Mi, request 32Mi, env [] and env_from []. State is OOMKilled with BackOff events.
- `kubernetes_pod_logs`: Latest instance log (previous instance's logs were gone): "building monthly report: loading 200MB of rows". That is far above the 48Mi limit.
- `kubernetes_recent_changes`: The only reports change is revision 1 (created). No rollout is behind the crash loop.
- `incidents_search`: Past incident 5b0e2c4e (2026-09-28) on demo/reports: OOMKilled at 48Mi because REPORTS_BATCH_SIZE was unset. Setting REPORTS_BATCH_SIZE=1000 fixed it. I did not open the full report.

**Recommendations**
1. Set REPORTS_BATCH_SIZE=1000 (as in the past fix) on the reports Deployment so rows are streamed in batches. Put it in the manifest or GitOps source so it persists.
2. Check that the app actually reads REPORTS_BATCH_SIZE. Then, if needed, raise the memory limit above 48Mi with headroom (peak plus about 25%), though the past fix shows a bigger limit alone only delays the OOM.
3. Do not just restart the pod; a restart will not fix an OOM crash loop.
4. Treat the checkout (DATABASE_URL removed in revision 2) and frontend (nonexistent image tag nginx:1.99.99-does-not-exist) failures as separate issues.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "reports"}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 30}
