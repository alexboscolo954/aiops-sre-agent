## Pod checkout-869fc5bcc6-db5ps is crash looping because revision 2 of the checkout deployment dropped the DATABASE_URL env var, and the app exits at startup with "FATAL: required env var DATABASE_URL is not set". The reports pod is OOMKilled and frontend is in ErrImagePull, but those are separate issues and do not explain this alert.

**Root cause** (high confidence, `bad_rollout`): Checkout revision 2 (created about 36s before the alert) removed the DATABASE_URL environment variable from the app container. Revision 1 had it. The app fails its startup check on the missing variable and exits with code 1, so the pod restarts in a loop.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_pod_logs`: Previous-instance log shows "FATAL: required env var DATABASE_URL is not set" followed by "checkout starting, version 1.4.0"; the app exits with code 1 (Error).
- `kubernetes_recent_changes`: checkout revision 2 rollout at 48s ago with diff env_removed: app: [DATABASE_URL]; revision 1 was created 2m ago.
- `kubernetes_describe_deployment`: Revision 1 (replicaset checkout-67d9799c78) config had env [DATABASE_URL]; current revision 2 has env []. Deployment Available=False, MinimumReplicasUnavailable, replicas 0/1 ready.
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps is Running but 0/1 ready, restarts 3, last terminated Error exit code 1.

**Recommendations**
1. Roll back checkout to revision 1 (kubectl rollout undo deployment/checkout -n demo --to-revision=1), which restores DATABASE_URL. This needs human approval.
2. Alternatively, restore the DATABASE_URL env var in the checkout deployment spec from its source (e.g. Secret or ConfigMap) and roll out a fix. Confirm the correct value source first.
3. After the rollout, confirm the checkout pod is 1/1 Ready and restarts stop.
4. Check why revision 2 dropped the variable (Helm values, GitOps manifest, or a manual edit) so it does not recur.
5. Separately: reports pod is OOMKilled at a 64Mi-class limit (check its memory limit and usage), and frontend has a nonexistent image tag nginx:1.99.99-does-not-exist. Both need their own fixes.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_recent_changes`
4. `kubernetes_pod_logs`
5. `kubernetes_describe_deployment`
