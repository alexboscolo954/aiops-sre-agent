## orders-api is crash-looping (exit 1, 3 restarts). At startup it calls inventory's /stock and gets a 404. That started after inventory's revision 2 rollout about 48s ago, and inventory now serves /v2/stock.

**Root cause** (high confidence, `bad_rollout`): inventory revision 2, rolled out about 48s ago, added the API_VERSION env var. The new inventory pod logs 'inventory serving /v2/stock'. orders-api 2.3.0 still calls GET http://inventory.orders:8080/stock, gets HTTP 404, and exits with 'FATAL: stock sync failed'. The likely cause is that the API version change moved the endpoint orders-api depends on; the 404 and the new path point to it, but this was not tested directly.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 is Running but 0/1 ready, 3 restarts, last terminated with Error exit code 1
- `kubernetes_pod_logs`: orders-api: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404'; inventory: 'inventory serving /v2/stock'
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago, adding the API_VERSION env var; orders-api has not changed since it was created

**Recommendations**
1. Roll back inventory to revision 1, or set API_VERSION so it serves /stock again. This needs approval.
2. Once inventory is back, confirm orders-api becomes ready.
3. Later, update orders-api to call /v2/stock before rolling inventory v2 out again.

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "tail_lines": 50}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 30}
