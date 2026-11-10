## The reports pod in demo is crash looping because it keeps getting OOMKilled (exit 137) at its 48Mi memory limit. The monthly report job loads about 200MB of rows into memory at once. REPORTS_BATCH_SIZE isn't set on the deployment, so the job doesn't load the rows in batches. A past incident (OPS-112) had the same cause and fix.

**Root cause** (high confidence, `bad_config`): The reports container has a 48Mi memory limit and an empty env list, so REPORTS_BATCH_SIZE is not set. Its log says 'building monthly report: loading 200MB of rows', and the container is OOMKilled with exit code 137. The past incident report says that without REPORTS_BATCH_SIZE the job loads the whole table, and that REPORTS_BATCH_SIZE=1000 makes it stream the rows and stay under 40Mi. That report also says raising the memory limit on 2026-08-30 only helped until the table grew. The deployment has a single revision, created 2m ago, so no rollout is to blame.
**Severity:** medium  ·  **Affected:** demo/deployment/reports

**Evidence**
- `kubernetes_list_pods`: Pod reports-55b4fffc66-hmq7f: 0/1 ready, 3 restarts, last terminated OOMKilled with exit code 137
- `kubernetes_pod_logs`: Last log line from reports-55b4fffc66-hmq7f: 'building monthly report: loading 200MB of rows' (previous logs were gone, so this is the latest instance)
- `kubernetes_describe_deployment`: reports app container: memory limit 48Mi, request 32Mi, env: [] (no REPORTS_BATCH_SIZE); only revision 1, created 2m ago
- `incidents_read`: Past report 5b0e2c4e (OPS-112, 2026-09-28): same OOMKill at 48Mi caused by missing REPORTS_BATCH_SIZE. The fix was REPORTS_BATCH_SIZE=1000; raising the limit had only delayed the next OOM.

**Recommendations**
1. Set REPORTS_BATCH_SIZE=1000 on deploy/reports in the team's manifests (source of truth) and roll it out.
2. Don't just raise the memory limit. In the past incident that only delayed the next OOM as the table grew.
3. Restarting the pod won't fix the crash loop, so don't do it.
4. After the rollout, check that the pod stays Ready with no new OOMKills. Then follow up on OPS-112 about why the env var was missing again, possibly because the manifest was reverted or redeployed without it.
5. Separately: other workloads in demo are also failing. checkout is crash looping with Error exit 1, and frontend is in ErrImagePull because the tag nginx:1.99.99-does-not-exist doesn't exist. Triage those on their own.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 50}
4. `incidents_search` {"keywords": "reports crashloop"}
5. `incidents_read` {"id": "5b0e2c4e-9a51-4d1e-8f3a-2f6c7d1e0a93"}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
