## The reports pod in demo is crash looping. It has been OOMKilled (exit 137) 3 times at its 48Mi memory limit while trying to load about 200MB of report rows in one go. REPORTS_BATCH_SIZE is not set on the container, which is the same cause a past incident found.

**Root cause** (high confidence, `bad_config`): The container's memory limit is 48Mi. Its only log line before being killed is 'building monthly report: loading 200MB of rows', and it ends OOMKilled with exit code 137. The container has no env vars at all, so REPORTS_BATCH_SIZE is unset. A past incident (2026-09-28) found that without that variable the job loads the whole table into memory, and that setting REPORTS_BATCH_SIZE=1000 makes it stream rows and stay under 40Mi. The same report says raising the limit on 2026-08-30 only held until the table grew. I haven't checked the batch-size behaviour in the code; it comes from the past report and matches what the pod shows now.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f container app: limits memory 48Mi, state and last_state both OOMKilled exit 137, 3 restarts, env: [] (no REPORTS_BATCH_SIZE)
- `kubernetes_pod_logs`: 'building monthly report: loading 200MB of rows' just before the kill (latest instance; previous logs were gone)
- `incidents_search`: Past incident 2026-09-28: same OOM at 48Mi, caused by unset REPORTS_BATCH_SIZE; setting it to 1000 keeps memory under 40Mi; raising the limit earlier did not last

**Recommendations**
1. Set REPORTS_BATCH_SIZE=1000 on the reports deployment (in source control or the manifest) and roll it out.
2. Check that the new pod stays under the 48Mi limit and stops restarting.
3. Don't fix this by raising the memory limit again: the past incident shows that only held until the table grew.
4. Add REPORTS_BATCH_SIZE as a required default in the manifest or in the app so it can't go missing again.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 50}
3. `incidents_search` {"keywords": "reports crashloop"}
