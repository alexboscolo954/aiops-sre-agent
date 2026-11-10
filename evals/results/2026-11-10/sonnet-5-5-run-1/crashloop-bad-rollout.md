## The checkout pod is crash looping because revision 2 removed the DATABASE_URL env var, so the app exits with code 1 at startup. Rolling back to revision 1 should fix it.

**Root cause** (high confidence, `bad_rollout`): Deployment checkout revision 2, rolled out about 48s before the check, removed the DATABASE_URL env var from the app container. Revision 1 had it and worked. The app logs 'FATAL: required env var DATABASE_URL is not set' and exits with code 1 on every start.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_recent_changes`: checkout revision 2 rolled out 48s ago, diff env_removed: app: [DATABASE_URL]. Revision 1 was created 2m ago.
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'FATAL: required env var DATABASE_URL is not set'. The previous instance's logs were gone, so this is the latest instance.
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps is 0/1 ready with 3 restarts. The app container's last termination was Error, exit code 1.
- `runbooks_runbook_for_alert`: The pod-crashlooping runbook lists missing config after a rollout as the most common cause. It says to roll back the revision and not to restart.

**Recommendations**
1. Roll back deployment demo/checkout to revision 1, or restore the DATABASE_URL env var (with its original value or secret reference) in the pod spec.
2. Check the manifest or GitOps source that produced revision 2 so the removal isn't reapplied.
3. After the fix, confirm the new checkout pod becomes Ready and restarts stop.
4. Don't just restart the pod. A restart doesn't fix a crash loop caused by missing config.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "checkout"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 30}
