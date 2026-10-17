## Pod checkout-7c856f898c-bjtfx (revision 2 of the checkout deployment) is crash looping because DATABASE_URL is not set. Revision 1 had that variable and still runs healthy, so the new revision dropped it.

**Root cause** (high confidence, `bad_rollout`): Revision 2 of deployment demo/checkout (ReplicaSet checkout-7c856f898c) has no DATABASE_URL env var. Revision 1 had it. The app exits with code 1 on startup with 'FATAL: required env var DATABASE_URL is not set'.
**Severity:** medium  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-7c856f898c-bjtfx

**Evidence**
- `kubernetes_pod_logs`: Previous run logs: 'checkout starting, version 1.4.0' then 'FATAL: required env var DATABASE_URL is not set'
- `kubernetes_describe_deployment`: Revision 2 (checkout-7c856f898c, created 36s ago) has env [] and env_from []. Revision 1 (checkout-7784c7f885) had env [DATABASE_URL].
- `kubernetes_list_pods`: checkout-7c856f898c-bjtfx is 0/1 ready, with 2 restarts and last terminated Error with exit code 1. The old revision pod checkout-7784c7f885-pwjtr is 1/1 Running.

**Recommendations**
1. Roll back deployment demo/checkout to revision 1 (kubectl rollout undo deployment/checkout -n demo). This restores DATABASE_URL.
2. Or fix the spec forward: re-add DATABASE_URL (from the original Secret or ConfigMap source) to the checkout container and roll out again.
3. Review the change that produced revision 2 to find out why the env var was removed, and add a check to stop it recurring.
4. Do not just restart the pod. A restart will not fix a missing env var.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_deployment`
4. `kubernetes_pod_logs`
