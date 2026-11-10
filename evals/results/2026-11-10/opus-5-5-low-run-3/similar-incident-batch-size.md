## reports-55b4fffc66-hmq7f in demo is crash looping. It is OOMKilled (exit 137) at its 48Mi memory limit because the monthly report tries to load about 200MB of rows into memory at once. The container has no env vars, so REPORTS_BATCH_SIZE is unset.

**Root cause** (high confidence, `bad_config`): The container has a 48Mi memory limit, and the job logs 'building monthly report: loading 200MB of rows'. Its env list is empty, so REPORTS_BATCH_SIZE is not set. The past incident 5b0e2c4e says that without this variable the job loads the whole table into memory. It also says raising the limit on 2026-08-30 only helped until the table grew, and that setting REPORTS_BATCH_SIZE=1000 streams the rows and keeps the job under 40Mi. Current tools confirm the variable is still missing and the pod is still OOMKilled. They can't show how the app reads the variable; that part comes only from the past report.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_describe_pod`: Container app: limits memory 48Mi, state and last_state both OOMKilled exit 137, 3 restarts, env [] (no REPORTS_BATCH_SIZE), BackOff events
- `kubernetes_pod_logs`: 'building monthly report: loading 200MB of rows' (previous logs were gone, so this is the latest instance)
- `incidents_read`: Past incident 5b0e2c4e (2026-09-28): same OOM at 48Mi. REPORTS_BATCH_SIZE was unset; raising the limit only held until the table grew; setting REPORTS_BATCH_SIZE=1000 fixed it

**Recommendations**
1. Set REPORTS_BATCH_SIZE=1000 on the reports deployment in its manifest or GitOps source so the env var isn't lost again, then let it roll out.
2. Check that the new pod stays below 48Mi and the report finishes without restarts.
3. Don't just raise the memory limit; the past incident shows that only works until the table grows again.
4. Find out why the variable is missing from the current spec, for example whether the earlier fix was never saved to the source or was reverted.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 50}
3. `incidents_search` {"keywords": "reports"}
