## The checkout pod is crash looping because revision 2, rolled out about 48s before the alert, removed the DATABASE_URL env var. The app exits with code 1 on startup.

**Root cause** (high confidence, `bad_rollout`): Deployment checkout revision 2 removed the DATABASE_URL env var from container 'app'. Revision 1 had it and worked. The app logs 'FATAL: required env var DATABASE_URL is not set' and exits 1, so the pod is in CrashLoopBackOff with 3 restarts.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_recent_changes`: checkout revision 2 rolled out 48s ago with diff env_removed: app: [DATABASE_URL]. Revision 1 was created 2m ago.
- `kubernetes_pod_logs`: checkout pod logs: 'FATAL: required env var DATABASE_URL is not set'
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps is 0/1 ready with 3 restarts. Last termination was Error, exit code 1.
- `runbooks_runbook_for_alert`: The pod-crashlooping runbook lists missing env config as the most common cause. Exit code 1 means the process itself failed.

**Recommendations**
1. Restore DATABASE_URL on the checkout deployment from secret checkout-db (secretKeyRef) and redeploy. Per Operator guidance, do not roll back the deployment.
2. Check that the pod becomes Ready and restarts stop.
3. Find out why the env var was removed from the deployment manifest or pipeline, and add a guard so required config can't be dropped.
4. Separate issues in the same namespace, not part of this alert: frontend has ErrImagePull on the nonexistent tag nginx:1.99.99-does-not-exist, and reports is OOMKilled.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "checkout"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 30}
