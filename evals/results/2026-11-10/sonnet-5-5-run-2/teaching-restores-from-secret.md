## The checkout pod is crash looping because revision 2, rolled out about 48s before the check, removed the DATABASE_URL env var. The app exits with code 1 at startup.

**Root cause** (high confidence, `bad_rollout`): Deployment checkout revision 2 removed the DATABASE_URL env var from the app container. Revision 1 had it and worked. The app logs 'FATAL: required env var DATABASE_URL is not set' and exits with code 1 on every start, which causes the restarts (3 so far).
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_recent_changes`: checkout revision 2 rolled out 48s ago with diff env_removed: app: [DATABASE_URL]; revision 1 was created 2m ago.
- `kubernetes_pod_logs`: 'FATAL: required env var DATABASE_URL is not set' (checkout starting, version 1.4.0).
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps is 0/1 ready with 3 restarts. Last terminated: Error, exit code 1.
- `runbooks_runbook_for_alert`: The pod-crashlooping runbook lists missing env config as the most common cause of exit code 1.

**Recommendations**
1. Restore DATABASE_URL on the checkout app container from secret checkout-db (secretKeyRef) and redeploy. Per Operator guidance, do not roll back the deployment.
2. Check that secret checkout-db exists in namespace demo and has the expected key.
3. Confirm the new pod becomes Ready and the restarts stop.
4. Add a review or CI check so required env vars are not dropped from the checkout manifest.
5. Unrelated to this alert: reports is OOMKilled (exit 137) and frontend has ErrImagePull (nginx:1.99.99-does-not-exist). Both need separate triage.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "checkout"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 30}
