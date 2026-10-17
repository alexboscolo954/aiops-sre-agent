## Pod checkout-7c856f898c-bjtfx (revision 2 of the checkout deployment) is crash looping because DATABASE_URL is not set. Revision 1 had that env var and its pod is healthy.

**Root cause** (high confidence, `bad_rollout`): Revision 2 of the checkout deployment (ReplicaSet checkout-7c856f898c) dropped the DATABASE_URL env var that revision 1 had. The app exits with code 1 at startup because it requires that variable.
**Severity:** medium  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-7c856f898c-bjtfx

**Evidence**
- `kubernetes_pod_logs`: Previous run logs: 'FATAL: required env var DATABASE_URL is not set'
- `kubernetes_describe_deployment`: Revision 2 (checkout-7c856f898c) has env [] and env_from []. Revision 1 (checkout-7784c7f885) had env [DATABASE_URL]. Both use image python:3.12-alpine.
- `kubernetes_list_pods`: checkout-7c856f898c-bjtfx is 0/1 ready with 2 restarts, terminated Error with exit code 1. The revision 1 pod checkout-7784c7f885-pwjtr is Running 1/1 with 0 restarts.

**Recommendations**
1. Roll back the checkout deployment to revision 1 (kubectl rollout undo deployment/checkout -n demo). This restores DATABASE_URL.
2. Or fix the manifest by re-adding DATABASE_URL, from the original Secret or ConfigMap source, to the app container, then roll out again.
3. Add a review or CI check so required env vars are not dropped from the deployment spec.
4. Do not restart the pod. A restart will not fix a missing env var.
5. Separate issues in the same namespace: reports is OOMKilled and frontend has an ErrImagePull for nginx:1.99.99-does-not-exist. Triage those separately.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_deployment`
4. `kubernetes_pod_logs`
