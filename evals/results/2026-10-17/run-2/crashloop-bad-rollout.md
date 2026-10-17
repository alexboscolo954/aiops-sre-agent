## The checkout pod checkout-7c856f898c-bjtfx is crash looping because revision 2 of the deployment dropped the DATABASE_URL env var. The app exits with code 1 at startup. Revision 1 had the variable and its pod is running.

**Root cause** (high confidence, `bad_rollout`): Deployment revision 2 (ReplicaSet checkout-7c856f898c) has no DATABASE_URL env var. Revision 1 defined it. The app logs 'FATAL: required env var DATABASE_URL is not set' and exits 1.
**Severity:** medium  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-7c856f898c-bjtfx

**Evidence**
- `kubernetes_pod_logs`: Previous run of checkout-7c856f898c-bjtfx: 'checkout starting, version 1.4.0' then 'FATAL: required env var DATABASE_URL is not set'
- `kubernetes_describe_deployment`: Revision 2 (checkout-7c856f898c, created 36s ago) has env [] and env_from []. Revision 1 (checkout-7784c7f885) had env [DATABASE_URL].
- `kubernetes_list_pods`: checkout-7c856f898c-bjtfx is 0/1 with 2 restarts, last terminated Error exit 1. The old revision pod checkout-7784c7f885-pwjtr is 1/1 Running.

**Recommendations**
1. Roll back deployment/checkout to revision 1: kubectl rollout undo deployment/checkout -n demo. Revision 1 has DATABASE_URL.
2. Or, if the removal was unintended, restore the DATABASE_URL env var (or its Secret/ConfigMap reference) in the deployment spec and re-roll.
3. Check the change that produced revision 2 to see why the env var was removed, and add a CI or manifest check for required env vars.
4. Do not simply restart the pod. A restart will not fix a missing-config crash loop.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_deployment`
4. `kubernetes_pod_logs`
