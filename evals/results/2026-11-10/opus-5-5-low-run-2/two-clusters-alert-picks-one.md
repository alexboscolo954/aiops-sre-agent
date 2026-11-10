## The reports pod in demo (prod-eu) keeps getting OOMKilled (exit code 137, 3 restarts). It loads about 200MB of rows, but its memory limit is only 48Mi.

**Root cause** (high confidence, `resource_limits`): The app container has a memory limit of 48Mi (request 32Mi). Its log says "building monthly report: loading 200MB of rows", so it needs about four times its limit, and the kernel OOM-kills it every time (exit code 137). The deployment was just created at revision 1, so no rollout caused this. The checkout rollout that removed DATABASE_URL is a different workload and doesn't explain an OOM. The logs don't show whether the job really needs all 200MB in memory at once or could stream the rows.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f container app: memory limit 48Mi, state terminated OOMKilled with exit code 137, 3 restarts, BackOff events
- `kubernetes_pod_logs`: Latest instance (previous logs are gone): 'building monthly report: loading 200MB of rows'
- `kubernetes_recent_changes`: reports was only created (revision 1) 2m ago. The only rollout was checkout revision 2, which removed DATABASE_URL and is unrelated to an OOM.

**Recommendations**
1. Raise the reports memory limit to fit the workload, e.g. at least 256Mi for a 200MB dataset, with a matching request. Do this in the deployment manifest or source repo.
2. Over the longer term, have the report job stream or batch the rows instead of loading all 200MB into memory.
3. After the change, check that the pod stays Running and no longer gets OOMKilled.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
2. `kubernetes_pod_logs` {"cluster": "prod-eu", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 50}
3. `kubernetes_recent_changes` {"cluster": "prod-eu"}
4. `incidents_search` {"keywords": "reports"}
