## checkout pod checkout-7c856f898c-bsjvj (revision 2) is crash looping. The app exits with code 1 because the required env var DATABASE_URL is not set. The pod was created 30s ago by a new rollout, and its spec has no env or envFrom.

**Root cause** (medium confidence, `crashloop_bad_config`): The revision 2 rollout (ReplicaSet checkout-7c856f898c) starts the container with no DATABASE_URL. The pod spec shows no env vars and no envFrom sources, and the app fails at startup with 'FATAL: required env var DATABASE_URL is not set'. I could not see revision 1's spec, so it is not confirmed that revision 2 removed the variable. Revision 1 (checkout-7784c7f885) is running 1/1 with 0 restarts.
**Severity:** medium  ·  **Affected:** demo/Deployment/checkout, demo/ReplicaSet/checkout-7c856f898c, demo/Pod/checkout-7c856f898c-bsjvj

**Evidence**
- `kubernetes_pod_logs`: checkout starting, version 1.4.0 / FATAL: required env var DATABASE_URL is not set
- `kubernetes_list_pods`: checkout-7c856f898c-bsjvj is 0/1 ready with 2 restarts, last terminated Error with exit code 1. The old revision 1 pod checkout-7784c7f885-rpff6 is 1/1 with 0 restarts.
- `kubernetes_describe_pod`: Container app has env: [] and env_from: []. The events show BackOff restarting the failed container, and there are no OOM or probe issues.
- `kubernetes_describe_deployment`: Revision 2 (checkout-7c856f898c) was created 30s ago, 5s after revision 1. The deployment is still progressing, and the Available condition is true because revision 1 is serving.

**Recommended actions**
1. Compare the revision 1 and revision 2 pod templates (for example kubectl rollout history deployment/checkout --revision=1 and --revision=2) to confirm DATABASE_URL was dropped in revision 2.
2. Fix the config: add DATABASE_URL to the deployment, via a Secret or ConfigMap reference, and roll out again.
3. If a quick fix is not possible, roll back with kubectl rollout undo deployment/checkout to revision 1, which is healthy. Do not just restart the pod, because a restart will not fix a missing env var.
4. Watch that the new ReplicaSet reaches Ready before the old one is scaled down, so checkout is not left without a healthy pod.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_pod_logs`
4. `kubernetes_describe_deployment`
5. `kubernetes_describe_pod`
