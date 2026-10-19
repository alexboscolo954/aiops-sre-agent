## checkout pod checkout-869fc5bcc6-db5ps is crash looping because revision 2 of the checkout Deployment removed the DATABASE_URL env var, and the app exits at startup when it is missing. Rolling back to revision 1, or restoring DATABASE_URL, should stop the loop.

**Root cause** (high confidence, `bad_rollout`): The checkout Deployment rolled out revision 2 about 48s before triage, and its diff shows env_removed for container app: [DATABASE_URL]. The app then logs 'FATAL: required env var DATABASE_URL is not set' and exits with code 1 (Error) on each start. Restarts are at 3 and the container state is terminated with exit code 1. Revision 1 was created about 2m earlier with no env diff, so it presumably still had DATABASE_URL. The failure is in the config, not the image, which is the same python:3.12-alpine that was already on the node. Previous-run logs were gone, so the fatal line comes from the latest instance.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_recent_changes`: checkout revision 2 'rollout' 48s ago with diff env_removed {app: [DATABASE_URL]}; checkout revision 1 'created' 2m ago with no diff.
- `kubernetes_pod_logs`: Latest instance logs: 'FATAL: required env var DATABASE_URL is not set' followed by 'checkout starting, version 1.4.0'. Previous-run logs were no longer available.
- `kubernetes_describe_pod`: Container app (image python:3.12-alpine) has state terminated Error, exit_code 1, restarts 3, and env list empty (env_from empty). BackOff event: 'Back-off restarting failed container app'.

**Recommendations**
1. Roll back the checkout Deployment to revision 1, which had DATABASE_URL (needs human approval; use kubectl rollout undo deployment/checkout -n demo or the equivalent).
2. Alternatively, re-add the DATABASE_URL env var (from its original Secret or ConfigMap reference) to the checkout Deployment and roll out a fixed revision.
3. After the fix, confirm the pod reaches Ready and restarts stop. Check that the frontend and reports Deployments, created in the same window, do not depend on the same missing config.
4. Fix the revision 2 change in source control so the env var removal is not re-applied on the next sync.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_describe_pod`
3. `kubernetes_recent_changes`
4. `kubernetes_pod_logs`
