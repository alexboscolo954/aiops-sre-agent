## The checkout pod in demo keeps crashing because revision 2 of the checkout deployment, rolled out about 48s ago, removed the DATABASE_URL env var. The app exits on startup with "FATAL: required env var DATABASE_URL is not set", and checkout has 0 of 1 replicas ready.

**Root cause** (high confidence, `bad_rollout`): Checkout revision 2 (ReplicaSet checkout-869fc5bcc6, about 48s ago) removed DATABASE_URL from container 'app'. Revision 2 has env: [] and revision 1 (checkout-67d9799c78) had env: [DATABASE_URL]. The image (python:3.12-alpine) did not change. Checkout 1.4.0 needs this variable and exits with code 1 when it is missing, so the pod has restarted 3 times.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout

**Evidence**
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps: ready 0/1, 3 restarts, last terminated Error with exit code 1
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps (previous run's logs were gone, so this is the latest run): 'checkout starting, version 1.4.0' then 'FATAL: required env var DATABASE_URL is not set'
- `kubernetes_recent_changes`: checkout revision 2 rolled out 48s ago; diff env_removed app: [DATABASE_URL]
- `kubernetes_describe_deployment`: Revision 2 (checkout-869fc5bcc6) has env [] and revision 1 (checkout-67d9799c78) had env [DATABASE_URL], with the same image python:3.12-alpine. Available=False (MinimumReplicasUnavailable)

**Recommendations**
1. Do not roll back the checkout deployment. Your standing instruction for a missing DATABASE_URL is to restore it from the secret instead.
2. Add DATABASE_URL back to container 'app' in deployment demo/checkout, sourced from secret checkout-db (valueFrom.secretKeyRef). I haven't checked that the secret or its key exists, so confirm that first. Then redeploy.
3. Watch the new rollout until checkout is 1/1 ready and the pod's restart count stops going up.
4. Find out why revision 2 dropped DATABASE_URL (manifest, chart or CI change) and fix it at the source so the next deploy doesn't remove it again.
5. Two other demo workloads are broken but are not part of this alert: frontend can't pull image nginx:1.99.99-does-not-exist (ErrImagePull), and reports is being OOMKilled. Triage them separately.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "checkout crash DATABASE_URL"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 30}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
