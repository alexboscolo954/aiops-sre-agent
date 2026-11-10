## demo/checkout is crash looping (exit 1). Revision 2 rolled out about 48s before the alert and removed the DATABASE_URL env var. The app now exits at startup with "FATAL: required env var DATABASE_URL is not set".

**Root cause** (high confidence, `bad_rollout`): Revision 2 of the checkout deployment, rolled out about 48s ago, removed the DATABASE_URL env var from the 'app' container. kubernetes_recent_changes shows this as env_removed: DATABASE_URL. The pod's container now has no env vars at all (env: []). Checkout version 1.4.0 needs this variable, so it logs "FATAL: required env var DATABASE_URL is not set" and exits with code 1. It has restarted 3 times and is in back-off. Revision 1 had the variable and is the last known-good revision.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout

**Evidence**
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'checkout starting, version 1.4.0' then 'FATAL: required env var DATABASE_URL is not set'. These are the latest instance's logs because the previous instance's logs were gone.
- `kubernetes_recent_changes`: checkout revision 2 rolled out 48s ago with diff env_removed app: [DATABASE_URL]; revision 1 was created 2m ago.
- `kubernetes_describe_pod`: Container app (python:3.12-alpine): env [] and envFrom [], terminated Error exit_code 1, restarts 3, BackOff warning events, Ready False.
- `runbooks_runbook_for_alert`: pod-crashlooping runbook: for exit 1, missing config or a new revision is the usual cause. Fix is to roll back or fix the config, not to restart.

**Recommendations**
1. Roll back demo/checkout to revision 1, which still has DATABASE_URL: kubectl -n demo rollout undo deployment/checkout --to-revision=1. This needs human approval.
2. Or restore the DATABASE_URL env var (from its Secret or ConfigMap) in the checkout deployment spec and roll it out again.
3. Check that the new pods become Ready and that the logs show a successful startup.
4. Find out why revision 2 dropped DATABASE_URL, then fix the manifest or pipeline so it doesn't happen again. Don't restart the pod: a restart won't fix the crash loop.

Runbook: `pod-crashlooping`

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 50}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "checkout crashloop"}
5. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
