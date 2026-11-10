## The checkout pod is crash looping because revision 2 of the deployment removed the DATABASE_URL env var, and the app exits at startup without it. Fix it by restoring DATABASE_URL from secret checkout-db and redeploying. Do not roll back.

**Root cause** (high confidence, `bad_rollout`): Checkout revision 2 rolled out about 48s before the alert and removed DATABASE_URL from container 'app'. Revision 1 had it and worked. The app logs 'FATAL: required env var DATABASE_URL is not set' and exits with code 1, so the pod restarts repeatedly (3 restarts) and stays 0/1 ready.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_recent_changes`: demo/checkout revision 2 rolled out 48s ago with diff env_removed: app: [DATABASE_URL]. Revision 1 was created 2m ago.
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps logs: 'FATAL: required env var DATABASE_URL is not set'. This is the latest instance's log, because the previous instance's logs were gone.
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps is 0/1 ready with 3 restarts, last terminated Error with exit code 1.
- `runbooks_runbook_for_alert`: The pod-crashlooping runbook lists missing config (an env var) as the most common cause of an Error exit. It says a restart does not fix a crash loop.

**Recommendations**
1. Restore the DATABASE_URL env var on the checkout container 'app', sourced from secret checkout-db (secretKeyRef), and redeploy.
2. Do not roll back the deployment. The Operator's guidance for a missing DATABASE_URL is to restore it from the secret and redeploy.
3. Confirm the new pod reaches 1/1 Ready and the restarts stop.
4. Add a check to the deploy pipeline or manifests so required env vars cannot be dropped from the checkout deployment.
5. Unrelated issues in the same namespace: frontend has ErrImagePull on nginx:1.99.99-does-not-exist, and reports is OOMKilled. Triage these separately.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "checkout"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 30}
