## orders-api is crash looping because inventory revision 2 now serves its API at /v2/stock, and orders-api still calls /stock, which returns 404. orders-api exits on startup when that call fails.

**Root cause** (high confidence, `bad_rollout`): inventory revision 2, rolled out 48s ago, added the API_VERSION env var. The new inventory pod logs 'inventory serving /v2/stock', so the stock endpoint has moved. orders-api calls GET http://inventory.orders:8080/stock, gets HTTP 404 Not Found, and exits with code 1 (FATAL: stock sync failed). That has happened 3 times, and it is now in BackOff. The Hub saw nothing failing before the change, and orders-api's containers only started at the time of the rollout (image pulled 48s ago). So the inventory rollout broke the endpoint path orders-api depends on.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_recent_changes`: inventory revision 2 rollout 48s ago, adding env var API_VERSION
- `kubernetes_pod_logs`: orders-api: 'GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found', then exit
- `kubernetes_pod_logs`: inventory: 'inventory serving /v2/stock'
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22: 0/1 ready, 3 restarts, last exit was Error code 1
- `kubernetes_get_events`: BackOff restarting failed container app in orders-api-568b7b8d9f-vzp22 (count 3)

**Recommendations**
1. Roll inventory back to revision 1, or remove/correct API_VERSION so it serves /stock again. Then confirm orders-api becomes Ready.
2. Or, if /v2 is intended, change orders-api's INVENTORY_URL or client to call /v2/stock before moving inventory to v2.
3. Coordinate future inventory API path changes with the services that call it, e.g. serve /stock and /v2/stock side by side during migration.

Runbook: `pod-crashlooping`

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "tail_lines": 50}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 50}
6. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
7. `incidents_search` {"keywords": "orders-api inventory API_VERSION"}
8. `runbooks_search_runbooks` {"keywords": "crashloop dependency"}
