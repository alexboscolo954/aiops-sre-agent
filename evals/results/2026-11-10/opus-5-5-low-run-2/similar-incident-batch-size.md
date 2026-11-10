## The reports pod in demo is crash looping because it gets OOMKilled at its 48Mi memory limit (exit 137, 3 restarts). The logs show it loading about 200MB of rows at once. REPORTS_BATCH_SIZE isn't set on the container, and a past incident traced the same crash to that missing variable.

**Root cause** (high confidence, `bad_config`): The monthly report job loads every row into memory at once ('loading 200MB of rows'), which is far above the container's 48Mi limit, so it is OOMKilled every time. The container sets no env vars at all, so REPORTS_BATCH_SIZE is unset. The past report from 2026-09-28 says that when this variable is unset the job reads the whole table in one go, and that REPORTS_BATCH_SIZE=1000 streams the rows and keeps the job under 40Mi. The same report says raising the limit on 2026-08-30 only held until the table grew. I didn't check this pod's rollout history, so it's possible a recent change dropped the variable.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_describe_pod`: Container app (python:3.12-alpine), memory limit 48Mi: state and last state both OOMKilled with exit code 137, 3 restarts, BackOff events, env list empty
- `kubernetes_pod_logs`: 'building monthly report: loading 200MB of rows' (from the latest run, because the previous run's logs were gone)
- `incidents_search`: Past incident 5b0e2c4e (2026-09-28): same OOM at 48Mi caused by unset REPORTS_BATCH_SIZE; the fix was REPORTS_BATCH_SIZE=1000, and raising the limit earlier only helped for a while

**Recommendations**
1. Set REPORTS_BATCH_SIZE=1000 on the reports deployment, for example with `kubectl -n demo set env deploy/reports REPORTS_BATCH_SIZE=1000`, and also make the change in its source manifests so it isn't lost.
2. Watch the new pod to confirm it stops getting OOMKilled and stays under about 40Mi.
3. Find out why the variable is missing. The past fix may not have been saved in the manifests, or a rollout may have removed it; `kubectl rollout history` on the deployment will show this.
4. Don't just raise the memory limit. The past report says that only held until the table grew.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true, "tail_lines": 50}
3. `incidents_search` {"keywords": "reports crashloop"}
