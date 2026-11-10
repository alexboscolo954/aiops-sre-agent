## After the inventory rev 2 rollout, orders-api crash-loops because inventory now serves /v2/stock and the /stock endpoint orders-api calls returns 404.

**Root cause** (medium confidence, `bad_rollout`): Inventory revision 2 added env var API_VERSION and now serves /v2/stock. Its logs say 'inventory serving /v2/stock'. orders-api (v2.3.0) still calls http://inventory.orders:8080/stock, gets a 404, exits with code 1 and restarts (3 restarts, BackOff). It is not an earlier failure. Before the change the old inventory pod had not become ready (readiness 'connection refused', plus a taint-related FailedScheduling), and the Hub saw nothing failing at that point. This is an inference from the logs and timings; I did not read inventory's full config.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'. inventory: 'inventory serving /v2/stock'.
- `kubernetes_recent_changes`: inventory rev 2 added env var API_VERSION 48s ago.
- `kubernetes_list_deployments`: orders-api is 0/1 ready with MinimumReplicasUnavailable.

**Recommendations**
1. Roll back inventory to revision 1, or remove or change API_VERSION, so that /stock is served again.
2. Alternatively, update orders-api to call /v2/stock, then redeploy it.
3. Confirm orders-api becomes 1/1 Ready and stops restarting.
4. Make API path changes backward compatible, for example by serving both /stock and /v2/stock during the transition.

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "tail_lines": 30}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 30}
6. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
