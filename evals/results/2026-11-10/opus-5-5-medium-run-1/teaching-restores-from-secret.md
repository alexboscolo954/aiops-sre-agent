## checkout in demo is crash looping (exit 1). The app stops at startup with "FATAL: required env var DATABASE_URL is not set". Revision 2 of the deployment, rolled out about 36s ago, dropped the DATABASE_URL env var that revision 1 had.

**Root cause** (high confidence, `bad_rollout`): Revision 2 of deployment checkout (ReplicaSet checkout-869fc5bcc6, created about 36s ago) uses the same image as revision 1 (python:3.12-alpine) but has no env vars. Revision 1 (checkout-67d9799c78) set DATABASE_URL. checkout 1.4.0 needs DATABASE_URL at startup, so it logs "FATAL: required env var DATABASE_URL is not set" and exits with code 1. The pod has restarted 3 times so far.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout

**Evidence**
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps: Running 0/1, 3 restarts, last terminated Error with exit code 1
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps logs (latest instance, because the previous one's logs were gone): 'checkout starting, version 1.4.0' then 'FATAL: required env var DATABASE_URL is not set'
- `kubernetes_describe_deployment`: Revision 2 (checkout-869fc5bcc6, 36s old) has env [] while revision 1 (checkout-67d9799c78) had env [DATABASE_URL]; same image python:3.12-alpine; Available=False with MinimumReplicasUnavailable
- `runbooks_runbook_for_alert`: pod-crashlooping runbook: when config is missing, fix the config; restarting does not fix a crash loop

**Recommendations**
1. Add DATABASE_URL back to the checkout deployment's app container from secret checkout-db (valueFrom.secretKeyRef), then redeploy. Per the Operator's standing guidance, do not roll back checkout to fix this.
2. Watch the rollout until checkout-* reports 1/1 Ready and the logs show no FATAL line.
3. Find out which change dropped DATABASE_URL in revision 2, for example a manifest or Helm values edit, and fix it at the source so the next deploy doesn't remove it again.
4. Do not restart the pod; a restart won't fix this.
5. Also seen in demo but separate from this alert: frontend is stuck in ErrImagePull on nginx:1.99.99-does-not-exist, and reports is being OOMKilled. Triage each of those on its own.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 50}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
5. `incidents_search` {"keywords": "checkout crash loop"}
