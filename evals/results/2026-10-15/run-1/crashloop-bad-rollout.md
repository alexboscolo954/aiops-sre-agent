## The checkout pod checkout-7c856f898c-bjtfx is crash looping. Deployment revision 2 dropped the DATABASE_URL env var, and the app exits at startup because it requires that variable. Revision 1 still has a healthy pod.

**Root cause** (high confidence, `bad_rollout`): Rollout revision 2 (ReplicaSet checkout-7c856f898c) removed the DATABASE_URL env var that revision 1 had. The app logs 'FATAL: required env var DATABASE_URL is not set' and exits with code 1.
**Severity:** medium  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-7c856f898c-bjtfx

**Evidence**
- `kubernetes_pod_logs`: Previous run logs: 'checkout starting, version 1.4.0' then 'FATAL: required env var DATABASE_URL is not set'
- `kubernetes_describe_deployment`: Revision 2 (checkout-7c856f898c) has env [] and env_from []. Revision 1 (checkout-7784c7f885) has env [DATABASE_URL]. The image is the same in both (python:3.12-alpine).
- `kubernetes_list_pods`: checkout-7c856f898c-bjtfx is 0/1 ready with 2 restarts, last terminated Error with exit code 1. The revision 1 pod checkout-7784c7f885-pwjtr is 1/1 Running.

**Recommendations**
1. Roll back deployment demo/checkout to revision 1 (kubectl rollout undo deployment/checkout -n demo), or restore the DATABASE_URL env var, or its Secret/ConfigMap reference, in the pod spec.
2. Find out why DATABASE_URL was removed from the manifest or pipeline in the latest change, and fix it at the source.
3. Add a CI check or startup validation so required config is present before a rollout.
4. Don't restart the pod. A restart does not fix a missing env var.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_deployment`
4. `kubernetes_pod_logs`
