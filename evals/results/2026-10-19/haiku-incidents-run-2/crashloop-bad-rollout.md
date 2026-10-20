## Pod checkout-869fc5bcc6-db5ps in demo is crash looping because checkout revision 2 removed the DATABASE_URL env var, and the app exits at startup with 'FATAL: required env var DATABASE_URL is not set'. Revision 1 had DATABASE_URL and ran fine, so rolling back to revision 1 is the fix.

**Root cause** (high confidence, `bad_rollout`): Deployment checkout revision 2 (ReplicaSet checkout-869fc5bcc6, created about 36-48s before the alert) dropped DATABASE_URL from container app. Revision 1 (ReplicaSet checkout-67d9799c78) had env [DATABASE_URL]. The current pod's logs show 'FATAL: required env var DATABASE_URL is not set' followed by 'checkout starting, version 1.4.0', and the container exits with code 1 (Error), restarts 3, back-off. The container env is now empty, so the app fails on startup. Confidence is high on the mechanism. The env var names come from the tool output, so the exact source of DATABASE_URL in revision 1 (direct env or secret) is not confirmed.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_pod_logs`: Latest instance logs: 'FATAL: required env var DATABASE_URL is not set' then 'checkout starting, version 1.4.0' (previous instance logs were no longer available).
- `kubernetes_describe_pod`: Container app state Error, exit_code 1, restarts 3, env [] and env_from []; Ready False (ContainersNotReady); BackOff event for failed container app.
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago with diff env_removed app: [DATABASE_URL].
- `kubernetes_describe_deployment`: Rollout history: revision 2 (checkout-869fc5bcc6) env [] created 36s ago, revision 1 (checkout-67d9799c78) env [DATABASE_URL] with 0 replicas; deployment Available False, MinimumReplicasUnavailable.
- `incidents_search`: No past Reports in the last 90 days matched checkout DATABASE_URL crashloop.

**Recommendations**
1. Roll back deployment checkout in namespace demo to revision 1 (ReplicaSet checkout-67d9799c78), which carried DATABASE_URL. This needs human approval.
2. Alternatively, restore the DATABASE_URL env var (from the same secret or configmap used in revision 1) on the checkout deployment's app container, then confirm the rollout.
3. After recovery, confirm the pod is Ready and restarts stop. Find out who removed DATABASE_URL in revision 2 and add a check so the env var is required in the chart or manifest.
4. Do not restart the pod. A restart does not fix a missing env var.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "container": null, "tail_lines": 100, "previous": true}
5. `incidents_search` {"keywords": "checkout DATABASE_URL crashloop", "days": 90, "limit": 5}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
