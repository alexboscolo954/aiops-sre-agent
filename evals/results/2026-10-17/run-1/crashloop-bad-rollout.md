## The checkout pod checkout-7c856f898c-bjtfx is crash looping. Revision 2 of the deployment dropped the DATABASE_URL env var, and the app exits at startup without it. Revision 1 still runs healthy.

**Root cause** (high confidence, `bad_rollout`): Deployment revision 2 (ReplicaSet checkout-7c856f898c) has no env vars. Revision 1 set DATABASE_URL. The checkout app logs 'FATAL: required env var DATABASE_URL is not set' and exits with code 1.
**Severity:** medium  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-7c856f898c-bjtfx

**Evidence**
- `kubernetes_pod_logs`: Previous run of checkout-7c856f898c-bjtfx: 'checkout starting, version 1.4.0' then 'FATAL: required env var DATABASE_URL is not set'.
- `kubernetes_describe_deployment`: Revision 2 (checkout-7c856f898c) has env [] and env_from []. Revision 1 (checkout-7784c7f885) had env [DATABASE_URL]. The image is the same in both.
- `kubernetes_list_pods`: checkout-7c856f898c-bjtfx is 0/1 ready with 2 restarts and last terminated Error (exit 1). Old pod checkout-7784c7f885-pwjtr is 1/1 Running.

**Recommendations**
1. Roll back the checkout deployment to revision 1 (kubectl rollout undo deployment/checkout -n demo). This restores DATABASE_URL and is low risk.
2. Or fix the manifest to restore DATABASE_URL (env or secretKeyRef) and redeploy.
3. Find out why the env var was dropped from the deployment spec, and add a CI check for required env vars.
4. Don't just restart the pod. A restart won't fix a missing config.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_pod_logs`
4. `kubernetes_describe_deployment`
