## checkout in demo is crash looping (exit 1). On startup it logs "FATAL: required env var DATABASE_URL is not set". Revision 2, rolled out about 36s ago, removed DATABASE_URL from the app container. Revision 1 had it.

**Root cause** (high confidence, `bad_rollout`): Deployment revision 2 (ReplicaSet checkout-869fc5bcc6, created 36s ago) changed the env vars of container 'app' from [DATABASE_URL] in revision 1 (checkout-67d9799c78) to none. The image stayed python:3.12-alpine. The app needs DATABASE_URL and exits with code 1 at startup without it, so the pod restarts in a loop (3 restarts) and the deployment has 0 of 1 replicas ready.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout

**Evidence**
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps logs: 'checkout starting, version 1.4.0' then 'FATAL: required env var DATABASE_URL is not set'. The previous run's logs were gone, so these are from the latest run.
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps: 0/1 ready, 3 restarts, last terminated Error with exit code 1
- `kubernetes_describe_deployment`: Revision 2 (checkout-869fc5bcc6, 36s old) has env []. Revision 1 (checkout-67d9799c78) had env [DATABASE_URL]. Same image python:3.12-alpine. Available=False (MinimumReplicasUnavailable).

**Recommendations**
1. Per Operator guidance, do not roll back checkout. Add DATABASE_URL back to the app container from secret checkout-db (env valueFrom secretKeyRef) and redeploy.
2. Watch the new pod reach Ready with no restarts, and check its logs: they should no longer show the DATABASE_URL error.
3. Find out which change dropped DATABASE_URL in revision 2 and fix it in the source manifests or GitOps repo so it doesn't come back.
4. Other problems in demo, not part of this alert: frontend is in ErrImagePull because the tag nginx:1.99.99-does-not-exist doesn't exist, and reports is being OOMKilled. Triage them separately.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 50}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
5. `incidents_search` {"keywords": "checkout crashloop DATABASE_URL"}
