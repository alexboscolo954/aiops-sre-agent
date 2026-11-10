**Passed:** Deployment inventory in orders has 1/1 replicas ready, and its only pod has 0 restarts. The pod is only 44s old because of a rollout to revision 2 about 48s ago, so it hasn't had long to prove stable. The separate orders-api deployment is failing, but the Check doesn't cover it.

**Evidence**
- `kubernetes_list_deployments`: inventory ready 1/1, updated 1, no problems. (orders-api is 0/1, outside this Check.)
- `kubernetes_list_pods`: inventory-b775d96fd-qq86l is Running, ready 1/1, restarts 0, running for 44s.
- `kubernetes_recent_changes`: inventory rolled out revision 2 about 48s ago, adding the env var API_VERSION. Revision 1 was created 2m ago. The new pod is healthy so far.

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
