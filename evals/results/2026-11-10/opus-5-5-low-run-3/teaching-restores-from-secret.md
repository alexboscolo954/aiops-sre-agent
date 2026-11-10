## checkout in demo is crash looping because revision 2, rolled out about 36 seconds ago, dropped the DATABASE_URL env var. The app exits with 'FATAL: required env var DATABASE_URL is not set', and the deployment has 0 of 1 replicas ready.

**Root cause** (high confidence, `bad_rollout`): Deployment revision 2 (ReplicaSet checkout-869fc5bcc6, created 36s ago) has no env vars on container app, so env is []. Revision 1 (checkout-67d9799c78) set DATABASE_URL. Without it, checkout 1.4.0 exits with code 1 at startup and has restarted 3 times.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout

**Evidence**
- `kubernetes_pod_logs`: Pod checkout-869fc5bcc6-db5ps logs (the previous run's logs were gone, so these are from the latest run): 'FATAL: required env var DATABASE_URL is not set'.
- `kubernetes_describe_deployment`: Revision 2 (36s ago) has env []. Revision 1 had env [DATABASE_URL]. Ready replicas: 0 of 1.
- `kubernetes_describe_pod`: Container app terminated with Error, exit code 1, 3 restarts, BackOff events. Pod env is empty.

**Recommendations**
1. Do not roll back. Per the Operator's standing instruction, restore DATABASE_URL on the checkout deployment from secret checkout-db (for example, a secretKeyRef to checkout-db), then redeploy.
2. Check that the new pod becomes Ready and that the logs no longer show the FATAL error.
3. Find out why the change that created revision 2 dropped the env var, and fix the source manifest so it doesn't happen again.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 50}
3. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
4. `incidents_search` {"keywords": "checkout crash DATABASE_URL"}
