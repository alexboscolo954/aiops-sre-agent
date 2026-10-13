## The checkout pod checkout-7c856f898c-bjtfx is crash looping. Revision 2 of the checkout deployment dropped the DATABASE_URL env var, and the app exits on startup without it. Revision 1 still has a healthy pod running.

**Root cause** (high confidence, `bad_rollout`): Deployment revision 2 (ReplicaSet checkout-7c856f898c) removed the DATABASE_URL env var that revision 1 had. The app logs 'FATAL: required env var DATABASE_URL is not set' and exits with code 1 on startup.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-7c856f898c-bjtfx

**Evidence**
- `kubernetes_pod_logs`: Previous run of checkout-7c856f898c-bjtfx: 'checkout starting, version 1.4.0' then 'FATAL: required env var DATABASE_URL is not set'.
- `kubernetes_describe_deployment`: Revision 2 (checkout-7c856f898c, created 36s ago) has env [] and env_from []. Revision 1 (checkout-7784c7f885) had env [DATABASE_URL].
- `kubernetes_list_pods`: The revision 2 pod has 0/1 ready, 2 restarts, and last terminated with Error exit code 1. The revision 1 pod checkout-7784c7f885-pwjtr is Running 1/1 with 0 restarts.

**Recommended actions**
1. Roll back the checkout deployment to revision 1 with `kubectl rollout undo deployment/checkout -n demo`. This restores DATABASE_URL.
2. Or fix the manifest to set DATABASE_URL again (env var or Secret/ConfigMap reference), then redeploy.
3. Find out why the env var was dropped from the deployment spec, and add a CI check or manifest validation for required env vars.
4. Do not just restart the pod. A restart will not fix a missing env var.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_pod_logs`
4. `kubernetes_describe_deployment`
