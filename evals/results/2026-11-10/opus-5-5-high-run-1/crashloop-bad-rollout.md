## checkout is in CrashLoopBackOff because rollout revision 2 (about 48s ago) removed the DATABASE_URL env var. The app exits on startup with 'FATAL: required env var DATABASE_URL is not set', so the deployment has 0 of 1 replicas ready and none available.

**Root cause** (high confidence, `bad_rollout`): Deployment checkout revision 2 (ReplicaSet checkout-869fc5bcc6) dropped the DATABASE_URL env var from container 'app'. Revision 1 (checkout-67d9799c78) had it. The image is the same in both (python:3.12-alpine), so only the env changed. Checkout 1.4.0 needs DATABASE_URL at startup and exits with code 1 without it. The pod has restarted 3 times.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout

**Evidence**
- `kubernetes_recent_changes`: checkout revision 2 rolled out 48s ago; the only change is env_removed: app: [DATABASE_URL]
- `kubernetes_describe_deployment`: Revision 2 (checkout-869fc5bcc6) has env [] while revision 1 (checkout-67d9799c78) had env [DATABASE_URL], both on python:3.12-alpine; Available=False with 0 of 1 ready
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'checkout starting, version 1.4.0' then 'FATAL: required env var DATABASE_URL is not set'. The previous run's logs were gone, so this is the latest run, which crashed the same way
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps is Running with 0/1 ready and 3 restarts; last terminated reason Error, exit code 1

**Recommendations**
1. Roll back checkout to revision 1 (kubectl rollout undo deployment/checkout -n demo --to-revision=1), or add DATABASE_URL (with its Secret or ConfigMap source) back to the deployment spec in the source manifests.
2. Find out why revision 2 removed DATABASE_URL, fix the manifest or Helm values so the next deploy doesn't remove it again, and add a CI check for required env vars.
3. Do not restart the pod. A restart won't fix this because the env var is missing from the pod template.
4. Other problems in demo, unrelated to this alert: frontend is stuck in ErrImagePull (tag nginx:1.99.99-does-not-exist) and reports is being OOMKilled. Triage them separately.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "checkout crash loop"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 50}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
