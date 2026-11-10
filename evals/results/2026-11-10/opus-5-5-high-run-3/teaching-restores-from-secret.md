## checkout-869fc5bcc6-db5ps in demo is crash looping (exit 1, 3 restarts) because checkout revision 2, rolled out about 48s ago, removed the DATABASE_URL env var. The app exits on startup with 'FATAL: required env var DATABASE_URL is not set'.

**Root cause** (high confidence, `bad_rollout`): Revision 2 of deployment demo/checkout (rolled out ~48s ago) removed env var DATABASE_URL from container 'app'. Revision 1 was created ~2m ago. checkout 1.4.0 requires DATABASE_URL at startup, so it logs 'FATAL: required env var DATABASE_URL is not set' and exits with code 1 every time. That gives the CrashLoop (pod ready 0/1, 3 restarts).
**Severity:** high  ·  **Affected:** demo/Deployment/checkout

**Evidence**
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps is Running but 0/1 ready with 3 restarts; last terminated reason is Error, exit_code 1.
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps logs: 'checkout starting, version 1.4.0' then 'FATAL: required env var DATABASE_URL is not set'. The previous run's logs were gone, so these are from the latest run.
- `kubernetes_recent_changes`: About 48s ago, demo/checkout revision 2 rolled out with diff env_removed {app: [DATABASE_URL]}. Revision 1 was created about 2m ago.
- `runbooks_runbook_for_alert`: The pod-crashlooping runbook says an Error exit means the process failed, that missing config is the most common cause and should be fixed in config, and that a restart won't fix it.

**Recommendations**
1. Put DATABASE_URL back on the checkout deployment's 'app' container, sourced from secret checkout-db (e.g. env DATABASE_URL valueFrom secretKeyRef name=checkout-db), then redeploy. Following the Operator's standing instruction, do not roll back the deployment for this.
2. Watch the new pods: they should log startup without the FATAL and reach Ready 1/1 with no more restarts.
3. Find out who removed DATABASE_URL in revision 2 and fix the source manifest or Helm values so the next deploy doesn't remove it again.
4. Don't restart the pod: that won't fix the missing config.
5. Two other pods in demo are failing and need their own triage: frontend has ErrImagePull on nginx:1.99.99-does-not-exist, and reports has OOMKilled restarts.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 50}
4. `kubernetes_recent_changes` {"cluster": "kind"}
5. `incidents_search` {"keywords": "checkout crash loop"}
