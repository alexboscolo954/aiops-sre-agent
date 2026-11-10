## The checkout pod in demo is crash looping (exit 1, 3 restarts). It started with revision 2 of the checkout deployment, rolled out about 48s ago, which dropped the DATABASE_URL env var. The app now stops at startup with 'FATAL: required env var DATABASE_URL is not set'.

**Root cause** (high confidence, `bad_rollout`): Revision 2 of deployment demo/checkout, rolled out about 48s before the alert, removed the env var DATABASE_URL from container 'app' (recent_changes diff: env_removed app: [DATABASE_URL]). Checkout 1.4.0 needs that variable and exits with code 1 on startup ('FATAL: required env var DATABASE_URL is not set'), so the pod keeps restarting. I didn't check revision 1's pod health directly. I'm assuming it was fine because it still had DATABASE_URL.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout

**Evidence**
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps: Running, 0/1 ready, 3 restarts, last terminated reason Error with exit_code 1
- `kubernetes_recent_changes`: checkout revision 2 rolled out 48s ago with diff env_removed {app: [DATABASE_URL]}. Revision 1 was created 2m ago.
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps logs (previous run's logs were gone, so these are from the current run): 'checkout starting, version 1.4.0' then 'FATAL: required env var DATABASE_URL is not set'

**Recommendations**
1. Roll back demo/checkout to revision 1 (kubectl rollout undo deployment/checkout -n demo --to-revision=1), or restore the DATABASE_URL env var (from its original Secret or ConfigMap source) in the deployment spec.
2. Check that the new pod becomes Ready and stops restarting, and that checkout can reach its database.
3. Find out why DATABASE_URL was removed in revision 2 and fix the source manifest or Helm values, so the next deploy doesn't remove it again.
4. Don't restart the pod: it would keep crashing until the env var is back.
5. Separately, two other demo workloads are failing: frontend can't pull image nginx:1.99.99-does-not-exist (ErrImagePull), and reports is being OOMKilled. These need their own triage.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "checkout crashloop"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 30}
