**Passed:** Deployment inventory in orders has 1/1 replicas ready, and its only pod has 0 restarts. The pod is 44s old because of a rollout to revision 2 about 48s ago, which added the env var API_VERSION. The separate orders-api deployment is failing, but the Check doesn't cover it.

**Evidence**
- `kubernetes_list_deployments`: inventory ready 1/1, updated 1, no problems. orders-api is 0/1 (MinimumReplicasUnavailable), which is out of scope.
- `kubernetes_list_pods`: Pod inventory-b775d96fd-qq86l is Running, ready 1/1, restarts 0, app running for 44s. orders-api pod orders-api-568b7b8d9f-vzp22 has 3 restarts and exit code 1, but it is not part of this Check.
- `kubernetes_recent_changes`: inventory rolled out revision 2 about 48s ago (env var API_VERSION added), which explains the young pod. It is a new pod from a rollout, not a restart.

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
