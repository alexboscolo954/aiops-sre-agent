## checkout pod checkout-7c856f898c-bjtfx is crash looping because revision 2 of the checkout Deployment dropped the DATABASE_URL env var, and the app exits on startup without it. Revision 1 still has DATABASE_URL and its pod checkout-7784c7f885-pwjtr is running 1/1, so rolling back to revision 1 (or restoring the env var) should fix it.

**Root cause** (high confidence, `bad_rollout`): The rollout to revision 2 (ReplicaSet checkout-7c856f898c) removed the DATABASE_URL environment variable that revision 1 (ReplicaSet checkout-7784c7f885) sets. The checkout app (version 1.4.0) fails fast with 'FATAL: required env var DATABASE_URL is not set', exit code 1, so the container crash-loops. The earlier revision with the variable is healthy.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-7c856f898c-bjtfx

**Evidence**
- `kubernetes_pod_logs`: Previous container log of checkout app: 'checkout starting, version 1.4.0' then 'FATAL: required env var DATABASE_URL is not set'.
- `kubernetes_describe_pod`: Container app: state terminated Error, exit_code 1, restarts 2; env list is empty and env_from is empty; BackOff event 'Back-off restarting failed container app'.
- `kubernetes_describe_deployment`: rollout_history: revision 2 (checkout-7c856f898c, created 36s ago) config env: [] ; revision 1 (checkout-7784c7f885, created 41s ago) config env: [DATABASE_URL].
- `kubernetes_list_pods`: checkout-7784c7f885-pwjtr (revision 1) Running 1/1, restarts 0; checkout-7c856f898c-bjtfx 0/1, restarts 2, exit code 1.

**Recommendations**
1. Roll back the checkout Deployment to revision 1 (kubectl rollout undo deployment/checkout -n demo, or the equivalent via your deploy tooling). This is the fastest fix and revision 1 is already serving traffic.
2. Do not restart the crashing pod; a restart will not fix a missing env var.
3. After the rollback, confirm the crash-looping pod is gone and the deployment is 1/1 ready.
4. Fix the revision 2 manifest by restoring the DATABASE_URL env var (from a Secret or ConfigMap, not a literal value) before rolling forward again, and check why it was dropped in the change.
5. Separately, the same namespace shows other failing pods that are not part of this alert: reports-7cc9978bbf-sq7r7 is OOMKilled (limit 64Mi area not verified) and frontend-79765fc9d-pqg7h is in ErrImagePull for nginx:1.99.99-does-not-exist. Triage them as their own alerts.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_describe_pod`
3. `kubernetes_list_pods`
4. `kubernetes_pod_logs`
5. `kubernetes_describe_deployment`
