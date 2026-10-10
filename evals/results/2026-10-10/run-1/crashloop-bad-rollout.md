## checkout pod checkout-7c856f898c-bsjvj (revision 2) is crash looping because DATABASE_URL is not set. Revision 2 dropped the env var that revision 1 had. The old pod is still serving, so impact is limited for now.

**Root cause** (high confidence, `bad_rollout`): Deployment revision 2 (ReplicaSet checkout-7c856f898c) has no DATABASE_URL env var. The app exits with code 1 at startup when it is missing. Revision 1 pods (checkout-7784c7f885) have DATABASE_URL defined. The container image is python:3.12-alpine in both revisions, so the env change is the likely difference.
**Severity:** medium  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-7c856f898c-bsjvj

**Evidence**
- `kubernetes_pod_logs`: checkout starting, version 1.4.0 / FATAL: required env var DATABASE_URL is not set
- `kubernetes_list_pods`: checkout-7c856f898c-bsjvj is 0/1 with 2 restarts, last terminated Error with exit code 1 (not OOM). The old pod checkout-7784c7f885-rpff6 is 1/1 with 0 restarts.
- `kubernetes_describe_deployment`: Revision 2 (checkout-7c856f898c) was created 30s ago, 5s after revision 1. The current spec has env: [] and env_from: [].
- `kubernetes_describe_pod`: The healthy revision 1 pod has the env var DATABASE_URL defined.

**Recommended actions**
1. Restore DATABASE_URL in the checkout deployment spec, either as a literal env var or from the Secret or ConfigMap that revision 1 used. Then let the rollout complete.
2. If a quick fix isn't available, roll back with `kubectl rollout undo deployment/checkout -n demo`. The rollout is stuck, so revision 1 keeps serving in the meantime.
3. Add a CI or manifest check that required env vars are present before rollout.
4. The runbook returned for this alert is oom-killed and does not apply to checkout. Separately, demo/reports is OOMKilled and demo/frontend has an ErrImagePull for nginx:1.99.99-does-not-exist. Both need their own triage.

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_pod_logs`
4. `kubernetes_describe_deployment`
5. `kubernetes_describe_pod`
