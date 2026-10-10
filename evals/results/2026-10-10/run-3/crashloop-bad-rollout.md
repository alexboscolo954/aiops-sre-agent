## The checkout pod checkout-7c856f898c-bjtfx (revision 2) is crash looping because it starts without the DATABASE_URL env var. Revision 1 had that variable and its pod is still healthy.

**Root cause** (high confidence, `bad_rollout`): Deployment revision 2 (ReplicaSet checkout-7c856f898c) dropped the DATABASE_URL env var that revision 1 defined. The app exits with code 1 at startup because the variable is missing.
**Severity:** medium  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-7c856f898c-bjtfx

**Evidence**
- `kubernetes_pod_logs`: Previous logs of checkout-7c856f898c-bjtfx: 'checkout starting, version 1.4.0 / FATAL: required env var DATABASE_URL is not set'
- `kubernetes_list_pods`: checkout-7c856f898c-bjtfx is 0/1 ready with 2 restarts and last terminated Error, exit code 1. The revision 1 pod checkout-7784c7f885-pwjtr is 1/1 Running with 0 restarts.
- `kubernetes_describe_deployment`: Revision 2 (created 36s ago) has env [] and env_from []. Revision 1 had env [DATABASE_URL]. The image is python:3.12-alpine in both revisions.

**Recommended actions**
1. Roll back the checkout deployment to revision 1 (kubectl rollout undo deployment/checkout -n demo), or re-add DATABASE_URL to the pod template (from a Secret or ConfigMap).
2. Find out why the env var was removed in the latest change to the manifest or Helm values, and fix it at the source so it is not re-applied.
3. Add a CI check or startup validation so a rollout that lacks required config fails before it replaces healthy pods.
4. Don't restart the pod. A restart will not fix a missing env var.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_pod_logs`
4. `kubernetes_describe_deployment`
