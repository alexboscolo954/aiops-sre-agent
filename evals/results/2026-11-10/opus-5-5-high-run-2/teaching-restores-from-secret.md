## checkout pod checkout-869fc5bcc6-db5ps in demo is crash looping (exit 1, 3 restarts) because revision 2 of the checkout deployment, rolled out 48s ago, removed the DATABASE_URL env var. The app now exits at startup with 'FATAL: required env var DATABASE_URL is not set'.

**Root cause** (high confidence, `bad_rollout`): Checkout deployment revision 2, rolled out about 48s before the crash loop, removed env var DATABASE_URL from container 'app' (diff env_removed: [DATABASE_URL]). Checkout 1.4.0 needs this variable and exits with code 1 at startup when it is missing ('FATAL: required env var DATABASE_URL is not set').
**Severity:** high  ·  **Affected:** demo/Deployment/checkout

**Evidence**
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps: Running, 0/1 ready, 3 restarts, last terminated reason Error with exit_code 1
- `kubernetes_pod_logs`: 'checkout starting, version 1.4.0' then 'FATAL: required env var DATABASE_URL is not set'. The previous instance's logs were gone, so these lines are from the latest instance.
- `kubernetes_recent_changes`: checkout revision 2 rolled out 48s ago with diff env_removed {app: [DATABASE_URL]}; revision 1 was created 2m ago

**Recommendations**
1. Do not roll back the checkout deployment (Operator teaching). Instead, put DATABASE_URL back on the checkout container 'app' from secret checkout-db with a secretKeyRef, then redeploy.
2. Watch the new rollout and confirm checkout pods become Ready 1/1 with no further restarts. A restart alone will not fix this.
3. Find out why revision 2 dropped DATABASE_URL (manifest or pipeline change) and fix it at the source so the next deploy doesn't remove it again.
4. Separately, demo has two other failing workloads that this alert doesn't cover: frontend is in ErrImagePull on nginx:1.99.99-does-not-exist, and reports is being OOMKilled. Triage them on their own.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 50}
4. `kubernetes_recent_changes` {"cluster": "kind"}
5. `incidents_search` {"keywords": "checkout crash loop"}
