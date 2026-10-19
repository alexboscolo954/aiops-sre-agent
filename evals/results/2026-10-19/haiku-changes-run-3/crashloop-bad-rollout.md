## checkout pod is crash looping because revision 2 of the checkout deployment removed the DATABASE_URL env var from the app container; the app exits at startup with "FATAL: required env var DATABASE_URL is not set". Two other demo pods are also failing for separate reasons: reports is OOMKilled and frontend has an ErrImagePull on a nonexistent nginx tag.

**Root cause** (high confidence, `bad_rollout`): Checkout revision 2 (rollout ~48s before the alert) dropped the DATABASE_URL environment variable that revision 1 set. The app fails fast at startup on the missing required variable, so the container exits with code 1 and Kubernetes backs off restarts. Revision 1 had the variable, so rolling back is the direct fix.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout

**Evidence**
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps app container logs: "FATAL: required env var DATABASE_URL is not set" followed by "checkout starting, version 1.4.0"
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps: 0/1 ready, restarts=3, last terminated Error exit code 1
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago, diff env_removed app: [DATABASE_URL]; revision 1 created 2m ago
- `kubernetes_describe_deployment`: checkout current revision 2 has env: [] and env_from: []; revision 1 config had env [DATABASE_URL]; Available=False, MinimumReplicasUnavailable

**Recommendations**
1. Roll back the checkout deployment to revision 1 (kubectl rollout undo deployment/checkout -n demo), which restores DATABASE_URL, or re-add DATABASE_URL to the app container env from its original source (ConfigMap/Secret).
2. Confirm checkout pod becomes Ready and restarts stop.
3. Check why DATABASE_URL was dropped from the revision 2 manifest/Helm values so it does not recur.
4. Separately: reports deployment pod is OOMKilled (limit too low or leak); follow the oom-killed runbook and compare memory usage with its limit.
5. Separately: frontend deployment references image nginx:1.99.99-does-not-exist, which does not exist; correct the image tag to a valid one.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_recent_changes`
4. `kubernetes_pod_logs`
5. `kubernetes_describe_deployment`
