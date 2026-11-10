## The checkout pod is crash looping because revision 2 removed the DATABASE_URL env var, so the app exits with code 1 at startup. Rolling back to revision 1 should fix it.

**Root cause** (high confidence, `bad_rollout`): Checkout revision 2 rolled out about 48s before the check. It removed the DATABASE_URL env var from the app container. Revision 1 had it and worked. The app now logs 'FATAL: required env var DATABASE_URL is not set' and exits with code 1, which causes the restart loop.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_recent_changes`: checkout revision 2 rolled out 48s ago with diff env_removed: app: [DATABASE_URL]. Revision 1 was created 2m ago.
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps logs: 'FATAL: required env var DATABASE_URL is not set'.
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps is 0/1 ready with 3 restarts. The app container's last termination was Error, exit code 1.

**Recommendations**
1. Roll back deployment/checkout to revision 1, or restore the DATABASE_URL env var (value or secret ref) in the pod spec.
2. After the fix, confirm the new pod becomes Ready and stops restarting.
3. Add a CI or manifest check that required env vars are present before rollout.
4. Separate issues in the same namespace, not part of this alert: frontend has an ErrImagePull because tag nginx:1.99.99-does-not-exist does not exist, and reports is OOMKilled.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "checkout"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 30}
