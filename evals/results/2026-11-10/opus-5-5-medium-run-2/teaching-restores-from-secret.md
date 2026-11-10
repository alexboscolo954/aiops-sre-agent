## checkout in demo is crash looping (exit 1) because revision 2, rolled out about 36s ago, dropped the DATABASE_URL env var. The app exits on startup with 'FATAL: required env var DATABASE_URL is not set'.

**Root cause** (high confidence, `bad_rollout`): Revision 2 of deployment checkout (ReplicaSet checkout-869fc5bcc6, created 36s ago) removed the DATABASE_URL env var. Revision 1 (checkout-67d9799c78, created 2m ago) had it. Both revisions run the same image, python:3.12-alpine. checkout 1.4.0 needs DATABASE_URL at startup and exits with code 1 without it. The deployment now has 0/1 replicas ready.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout

**Evidence**
- `kubernetes_pod_logs`: Pod checkout-869fc5bcc6-db5ps logs: 'checkout starting, version 1.4.0' then 'FATAL: required env var DATABASE_URL is not set'. The previous run's logs were gone, so these are from the latest run.
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps is 0/1 ready with 3 restarts. Last termination: Error, exit code 1.
- `kubernetes_describe_deployment`: Revision 2 (checkout-869fc5bcc6, 36s old) has env: []. Revision 1 (checkout-67d9799c78) had env ['DATABASE_URL']. Same image in both. Available=False with MinimumReplicasUnavailable.

**Recommendations**
1. Per the Operator's standing instruction, do not roll back checkout. Instead, restore DATABASE_URL on the checkout deployment from secret checkout-db (env valueFrom secretKeyRef pointing at secret checkout-db) and redeploy.
2. Check that secret checkout-db exists in namespace demo and has the expected key before applying the change.
3. Find out who made the revision 2 change and fix the source manifest (Git/Helm values) so the env var isn't dropped again.
4. Don't restart the pod: a restart won't fix a missing env var.
5. Other problems in demo, not part of this alert: frontend is stuck on ErrImagePull because its image tag nginx:1.99.99-does-not-exist doesn't exist, and reports is being OOMKilled. Triage them separately.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 50}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
5. `incidents_search` {"keywords": "checkout crash loop"}
