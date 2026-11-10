## checkout pod crash-loops (exit 1) because revision 2, rolled out about 48s ago, removed the DATABASE_URL env var. The app exits at startup without it.

**Root cause** (high confidence, `bad_rollout`): Deployment checkout revision 2 removed env var DATABASE_URL from container 'app'. Revision 1 had it and worked. The app logs 'FATAL: required env var DATABASE_URL is not set' and exits 1 at startup, so the pod crash-loops and never becomes ready.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_recent_changes`: checkout revision 2 rolled out 48s ago with diff env_removed: app: [DATABASE_URL]; revision 1 was created 2m ago.
- `kubernetes_pod_logs`: checkout app logs: 'FATAL: required env var DATABASE_URL is not set'.
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps is 0/1 ready with 3 restarts, last terminated Error with exit code 1 (not OOM).
- `runbooks_runbook_for_alert`: The pod-crashlooping runbook lists missing config after a rollout as the top cause. It says to roll back the revision and not to restart.

**Recommendations**
1. Roll back deployment demo/checkout to revision 1, or restore the DATABASE_URL env var (with its original value or secret reference) in the pod spec.
2. After the rollback, confirm the checkout pod reaches 1/1 Ready and restarts stop.
3. Find out why DATABASE_URL was removed from the manifest (a bad edit or a Helm/GitOps values change) and add a check so required env vars can't be dropped.
4. Don't just restart the pod: it will keep crashing until the config is restored.
5. Separate issues in the same namespace: frontend has ErrImagePull on nginx:1.99.99-does-not-exist, and reports is OOMKilled. Neither is related to this alert.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "checkout"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 30}
