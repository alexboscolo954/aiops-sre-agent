## Pod checkout-869fc5bcc6-db5ps is crash looping (exit 1, 3 restarts) because revision 2 of the checkout deployment removed the DATABASE_URL env var, and the app exits at startup with 'FATAL: required env var DATABASE_URL is not set'. This is a bad rollout; rolling back to revision 1 should fix it.

**Root cause** (high confidence, `bad_rollout`): Checkout revision 2 (ReplicaSet checkout-869fc5bcc6, created about 36s before the alert) removed DATABASE_URL from the app container's env (recent_changes diff: env_removed app: [DATABASE_URL]). Revision 1 (checkout-67d9799c78) had DATABASE_URL set and is now scaled to 0. The current pod's container exits with code 1 and the log shows the fatal missing-env-var error at startup, so the crash is caused by the missing config, not by resources or the image. Image python:3.12-alpine is unchanged between revisions.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_pod_logs`: previous-instance logs gone; latest instance shows 'FATAL: required env var DATABASE_URL is not set' then 'checkout starting, version 1.4.0'
- `kubernetes_describe_pod`: container app state terminated Error, exit_code 1, restarts 3; env list is empty; BackOff event 'Back-off restarting failed container app'
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago with diff env_removed app: [DATABASE_URL]; revision 1 created 2m ago
- `kubernetes_describe_deployment`: revision 2 (checkout-869fc5bcc6) config app env [] with 1 replica ready 0; revision 1 (checkout-67d9799c78) config env [DATABASE_URL], replicas 0; Available=False MinimumReplicasUnavailable
- `incidents_search`: no past incidents matched checkout DATABASE_URL crashloop in the last 90 days

**Recommendations**
1. Roll back the checkout deployment to revision 1 (ReplicaSet checkout-67d9799c78), which had DATABASE_URL set. This is the fix; restarting the pod will not help.
2. Alternatively, restore DATABASE_URL in the checkout deployment's env or envFrom (from the same Secret/ConfigMap used by revision 1) and roll out again.
3. Confirm the checkout deployment becomes Available and the pod stops restarting; check that the app logs show it starting without the FATAL line.
4. Find out why DATABASE_URL was removed in revision 2 (the change that produced it) so the config source is kept in the chart or manifest.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "container": "app", "previous": true, "tail_lines": 30}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
6. `incidents_search` {"keywords": "checkout DATABASE_URL crashloop", "days": 90, "limit": 5}
