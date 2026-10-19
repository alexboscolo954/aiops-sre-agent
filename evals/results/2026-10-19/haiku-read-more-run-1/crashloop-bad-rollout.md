## Checkout pod checkout-869fc5bcc6-db5ps is crash looping with exit code 1 because the DATABASE_URL env var is missing. Revision 2 of the checkout deployment, rolled out about 48 seconds before the alert, removed DATABASE_URL, and the app exits at startup when it is absent. Rolling back to revision 1 should fix it.

**Root cause** (high confidence, `bad_rollout`): Checkout revision 2 (ReplicaSet checkout-869fc5bcc6, created 36s before the investigation) dropped the DATABASE_URL env var that revision 1 (checkout-67d9799c78) set. The recent_changes diff shows env_removed app: [DATABASE_URL]. The container's previous log says "FATAL: required env var DATABASE_URL is not set" and then the app exits with code 1 (Error), so the pod restarts repeatedly (restarts: 3, 0/1 ready). The deployment shows Available=False with MinimumReplicasUnavailable.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps app container logs: "FATAL: required env var DATABASE_URL is not set" followed by "checkout starting, version 1.4.0".
- `kubernetes_recent_changes`: demo checkout revision 2 rollout 48s ago with diff env_removed {app: [DATABASE_URL]}; revision 1 created 2m ago.
- `kubernetes_describe_deployment`: checkout rollout_history: revision 2 (checkout-869fc5bcc6) env [] vs revision 1 (checkout-67d9799c78) env [DATABASE_URL]; Available=False, MinimumReplicasUnavailable; replicas desired 1, ready 0.
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps: ready 0/1, restarts 3, last terminated Error exit code 1.

**Recommendations**
1. Roll back the checkout deployment to revision 1 (checkout-67d9799c78), which had DATABASE_URL set. This needs human approval because it is a change.
2. Alternatively, restore DATABASE_URL in the checkout deployment's env, sourced from the same Secret or ConfigMap that revision 1 used.
3. After the rollback, confirm the checkout pod reaches 1/1 Ready and restarts stop.
4. Find out why revision 2 dropped DATABASE_URL (a manifest or Helm values change) so the next deploy does not repeat it.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_recent_changes`
4. `kubernetes_pod_logs`
5. `kubernetes_describe_deployment`
