## checkout pod checkout-869fc5bcc6-db5ps is crash looping because revision 2 of the checkout deployment removed the DATABASE_URL env var from container 'app'. The app exits on startup with 'FATAL: required env var DATABASE_URL is not set'. Restarting will not help; the fix is to restore the env var or roll back to revision 1.

**Root cause** (high confidence, `bad_rollout`): Checkout rollout revision 2 (about 48s before the alert) dropped DATABASE_URL from the app container's env. On startup the app checks for DATABASE_URL, finds it missing, and exits with code 1, so the pod enters CrashLoopBackOff.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago with diff env_removed app: [DATABASE_URL]; revision 1 created 2m ago with no diff.
- `kubernetes_pod_logs (previous=true, falls back to latest instance)`: 'FATAL: required env var DATABASE_URL is not set' followed by 'checkout starting, version 1.4.0'.
- `kubernetes_describe_pod`: Container app: state terminated Error, exit_code 1, restarts 3, env list empty and env_from empty; Ready False with ContainersNotReady; BackOff event 'Back-off restarting failed container app'.

**Recommendations**
1. Roll back the checkout deployment to revision 1 (kubectl rollout undo deployment/checkout -n demo), which had DATABASE_URL, or re-add DATABASE_URL to the app container env in revision 2. Requires human approval before running.
2. Confirm the rollback clears the crash loop: pods reach Ready and restarts stop.
3. Find out why revision 2 dropped DATABASE_URL (chart values, manifest or CI change) and add a check so a missing required env var fails the rollout before it ships.
4. Note: the env var value should come from the existing Secret or ConfigMap, not be typed into the manifest.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_describe_pod`
3. `kubernetes_recent_changes`
4. `kubernetes_pod_logs`
