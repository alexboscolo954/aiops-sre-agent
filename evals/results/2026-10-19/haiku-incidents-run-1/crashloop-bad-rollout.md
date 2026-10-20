## The checkout pod is crash looping because revision 2 of the checkout Deployment removed the DATABASE_URL environment variable. The app exits at startup with "FATAL: required env var DATABASE_URL is not set". Revision 1 had the variable, so this is a bad rollout.

**Root cause** (high confidence, `bad_rollout`): Checkout revision 2 (ReplicaSet checkout-869fc5bcc6, created about 36s before the alert) removed the DATABASE_URL env var from container app. kubernetes_recent_changes reports env_removed: {app: [DATABASE_URL]}. Revision 1 (checkout-67d9799c78) had env [DATABASE_URL] and is now scaled to 0. The current container has env: [] and env_from: []. Its logs show "FATAL: required env var DATABASE_URL is not set" before "checkout starting, version 1.4.0". The container exits with code 1 (Error) and restarts 3 times, so the pod is back-off looping and the deployment shows Available=False (MinimumReplicasUnavailable, ready 0/1). The memory limit of 64Mi is not implicated: the exit is a clean Error with exit code 1, not OOMKilled.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_pod_logs`: Previous/latest container log for checkout-869fc5bcc6-db5ps (app): "FATAL: required env var DATABASE_URL is not set" followed by "checkout starting, version 1.4.0".
- `kubernetes_describe_pod`: Container app: state terminated Error, exit_code 1, restarts 3, env [] and env_from [], limits memory 64Mi. Ready=False (ContainersNotReady); event BackOff "Back-off restarting failed container app".
- `kubernetes_recent_changes`: demo/checkout rollout revision 2 at 48s ago with diff env_removed {app: [DATABASE_URL]}; revision 1 created 2m ago with no diff.
- `kubernetes_describe_deployment`: rollout_history: revision 2 (checkout-869fc5bcc6, replicas 1, config env []) is current; revision 1 (checkout-67d9799c78, config env [DATABASE_URL], replicas 0). Available=False, MinimumReplicasUnavailable, replicas ready 0 of desired 1.
- `runbooks_runbook_for_alert`: pod-crashlooping runbook: Error exit with a new revision means roll back that revision; if config is missing, fix the config. A restart does not fix a crash loop.

**Recommendations**
1. Roll back demo/checkout to revision 1, which had DATABASE_URL, with kubectl rollout undo deployment/checkout -n demo. Alternatively, restore the DATABASE_URL env var (from the Secret or ConfigMap the revision 1 spec used) in the current revision.
2. Confirm the pod reaches Ready and the deployment shows Available=True, and that the checkout container no longer logs the FATAL message.
3. Find out why DATABASE_URL was removed in revision 2 (Helm values, GitOps manifest or manual edit) so the same change does not reach the next rollout.
4. Do not restart the pod; a restart will not fix a missing env var.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "container": "app", "previous": true, "tail_lines": 20}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
