## The checkout pod in the demo namespace is crash looping. Revision 2 of the checkout deployment, rolled out 36s ago, dropped the DATABASE_URL env var, so the app exits at startup with 'FATAL: required env var DATABASE_URL is not set'.

**Root cause** (high confidence, `bad_rollout`): Revision 1 (ReplicaSet checkout-67d9799c78, about 2m old) set the DATABASE_URL env var on container app. Revision 2 (ReplicaSet checkout-869fc5bcc6, 36s old) uses the same image, python:3.12-alpine, but has no env vars at all. The app checks for DATABASE_URL at startup and exits with code 1 when it's missing. The pod has restarted 3 times and the deployment has 0 of 1 replicas ready.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout

**Evidence**
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'checkout starting, version 1.4.0' then 'FATAL: required env var DATABASE_URL is not set'. These are the current run's logs because the previous run's logs were gone.
- `kubernetes_describe_deployment`: Revision 1 env: [DATABASE_URL]. Revision 2 (36s old) env: []. Same image. Ready 0/1, MinimumReplicasUnavailable.
- `kubernetes_describe_pod`: Container app: terminated Error, exit_code 1, 3 restarts, BackOff events. Env and envFrom are both empty.

**Recommendations**
1. Don't roll back the deployment; the Operator's guidance for this cause says not to.
2. Put DATABASE_URL back on container app, sourced from secret checkout-db (valueFrom secretKeyRef), and redeploy checkout.
3. Check that the new pod becomes Ready and the KubePodCrashLooping alert clears.
4. Find out which change removed DATABASE_URL in revision 2 and fix it in the source manifests so it doesn't happen again.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 30}
3. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
4. `incidents_search` {"keywords": "checkout crash"}
