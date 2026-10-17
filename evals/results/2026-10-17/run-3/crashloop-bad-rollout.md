## The checkout pod checkout-7c856f898c-bjtfx is crash looping because revision 2 of the deployment no longer sets DATABASE_URL. The app exits with code 1 at startup. Revision 1 had the variable and its pod is running and ready.

**Root cause** (high confidence, `bad_rollout`): Deployment revision 2 (ReplicaSet checkout-7c856f898c) dropped the DATABASE_URL env var that revision 1 had. The app checks for it at startup and exits 1 with 'required env var DATABASE_URL is not set'.
**Severity:** medium  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-7c856f898c-bjtfx

**Evidence**
- `kubernetes_pod_logs`: Previous container logs: 'checkout starting, version 1.4.0' then 'FATAL: required env var DATABASE_URL is not set'
- `kubernetes_describe_deployment`: Revision 2 (checkout-7c856f898c, created 36s ago) has env [] and env_from []. Revision 1 (checkout-7784c7f885) has env [DATABASE_URL].
- `kubernetes_list_pods`: checkout-7c856f898c-bjtfx is 0/1 ready with 2 restarts, last terminated Error with exit code 1. The revision 1 pod checkout-7784c7f885-pwjtr is 1/1 Running.

**Recommendations**
1. Roll back the checkout deployment to revision 1 (kubectl rollout undo deployment/checkout -n demo). This is the quickest fix and restores DATABASE_URL.
2. If revision 2 had a legitimate purpose, redeploy it with DATABASE_URL restored (value or secretKeyRef, as in revision 1).
3. Check the manifest or CI pipeline that produced revision 2 to find out why the env var was removed.
4. Add a rollout gate or CI check so that required env vars can't be dropped from the deployment spec.
5. Separate issues in the same namespace: reports is OOMKilled (see the oom-killed runbook) and frontend has ErrImagePull on nginx:1.99.99-does-not-exist. Neither is part of this alert.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_deployment`
4. `kubernetes_pod_logs`
