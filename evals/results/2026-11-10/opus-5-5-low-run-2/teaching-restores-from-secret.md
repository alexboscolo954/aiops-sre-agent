## checkout in demo is crash looping because revision 2, rolled out about 36s ago, removed the DATABASE_URL env var. The app exits on startup with 'FATAL: required env var DATABASE_URL is not set', so 0 of 1 replicas are ready.

**Root cause** (high confidence, `bad_rollout`): Revision 2 of the checkout deployment (ReplicaSet checkout-869fc5bcc6, created 36s ago) has no env vars. Revision 1 (checkout-67d9799c78) set DATABASE_URL. The image is the same in both revisions (python:3.12-alpine). Without DATABASE_URL, checkout 1.4.0 exits with code 1 at startup and has restarted 3 times.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout

**Evidence**
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps logs (previous run's logs were gone; tool showed the latest run): 'FATAL: required env var DATABASE_URL is not set' after 'checkout starting, version 1.4.0'
- `kubernetes_describe_deployment`: Revision 2 (36s old) has env []; revision 1 had env [DATABASE_URL]; same image; 0/1 ready
- `kubernetes_describe_pod`: Container app terminated with Error, exit code 1, 3 restarts, BackOff events, env empty

**Recommendations**
1. Per Operator guidance, do not roll back checkout. Restore DATABASE_URL in the checkout deployment from secret checkout-db (secretKeyRef) and redeploy.
2. Watch the new pods reach Ready and confirm the deployment shows 1/1 available.
3. Find out which change removed DATABASE_URL and fix the source (manifest or chart) so it doesn't come back.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 50}
3. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
4. `incidents_search` {"keywords": "checkout crash DATABASE_URL"}
