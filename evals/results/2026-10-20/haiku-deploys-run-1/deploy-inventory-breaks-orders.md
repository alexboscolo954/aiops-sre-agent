## Inventory revision 2 changed its API path to /v2/stock, but orders-api still calls http://inventory.orders:8080/stock, so it fails on startup with HTTP 404 and crash-loops (0/1 ready, 3 restarts). Inventory itself is up, but it logged readiness-probe failures during its rollout.

**Root cause** (medium confidence, `bad_rollout`): The inventory rollout to revision 2 (48s before the check, adding env API_VERSION) made inventory serve /v2/stock. orders-api 2.3.0 still requests /stock at startup, gets HTTP 404 and exits with code 1, so it restarts repeatedly. The orders-api failure appeared after the change, so it is not a pre-existing problem. The mismatch is inferred from the logs, not confirmed from the inventory code.
**Severity:** high  ·  **Affected:** orders/Deployment/inventory, orders/Deployment/orders-api

**Evidence**
- `kubernetes_recent_changes`: inventory revision 2 rollout 48s ago, env_added API_VERSION
- `kubernetes_pod_logs`: orders-api FATAL: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found
- `kubernetes_pod_logs`: inventory serving /v2/stock
- `kubernetes_list_pods`: orders-api 0/1 ready, restarts 3
- `kubernetes_get_events`: inventory readiness probe connection refused 44s and 47s ago

**Recommendations**
1. Roll inventory back to revision 1 (remove API_VERSION) so orders-api gets /stock again, or else fix orders-api's inventory path/config to use /v2/stock. Both are changes and need approval.
2. After the fix, confirm orders-api is 1/1 ready with no new restarts, and that inventory has no new readiness-probe warnings.
3. Check the orders-api source or config for the stock endpoint it calls, to confirm the path mismatch.

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders", "label_selector": ""}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders", "warnings_only": true}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "container": "app", "tail_lines": 50, "previous": true}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "container": "app", "tail_lines": 50, "previous": false}
7. `incidents_search` {"keywords": "orders-api inventory stock 404", "days": 90, "limit": 5}
8. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
