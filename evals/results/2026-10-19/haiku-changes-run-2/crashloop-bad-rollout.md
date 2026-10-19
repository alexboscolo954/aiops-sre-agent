## checkout pod checkout-869fc5bcc6-db5ps is crash looping with exit code 1 because the app exits at startup with "FATAL: required env var DATABASE_URL is not set". Checkout revision 2 was rolled out about 48s before the alert and removed the DATABASE_URL env var from the app container, so the bad rollout is the likely cause.

**Root cause** (high confidence, `bad_rollout`): Checkout revision 2 removed the DATABASE_URL environment variable from the app container. The app (version 1.4.0) refuses to start without it, exits with code 1, and Kubernetes backs off restarting it. Revision 1 did not have this problem.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_pod_logs`: Latest instance log: "FATAL: required env var DATABASE_URL is not set" followed by "checkout starting, version 1.4.0". The previous instance's logs were gone, so this is the latest run.
- `kubernetes_describe_pod`: Container app (image python:3.12-alpine) has terminated with Error, exit code 1, restarts: 3, and env: [] with no envFrom. Events show BackOff restarting failed container app.
- `kubernetes_recent_changes`: demo/checkout revision 2 rollout 48s before the alert, with diff env_removed app: [DATABASE_URL]. Revision 1 was created about 2m earlier with no diff.

**Recommendations**
1. Roll back demo/checkout to revision 1 (kubectl -n demo rollout undo deployment/checkout), which is the known-good revision. This needs human approval and was not run.
2. Alternatively, restore the DATABASE_URL env var (from a Secret or ConfigMap) in the checkout deployment spec, then roll out again.
3. Confirm the pods become Ready and the BackOff events stop. Then find out why revision 2 dropped DATABASE_URL (for example, a Helm values or manifest change) so it does not happen again.
4. Check whether the reports and frontend deployments, created in the same window, depend on checkout and are affected.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_describe_pod`
3. `kubernetes_pod_logs`
4. `kubernetes_recent_changes`
