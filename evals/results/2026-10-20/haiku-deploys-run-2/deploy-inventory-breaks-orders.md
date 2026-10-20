## Inventory revision 2 changed its API to /v2/stock (via new API_VERSION env var), so orders-api's unchanged stock call to /stock now returns 404. orders-api crash-loops with 0/1 ready. Inventory itself is healthy.

**Root cause** (medium confidence, `bad_rollout`): inventory revision 2 (rollout 48s ago, env added API_VERSION) serves /v2/stock. orders-api 2.3.0 still calls http://inventory.orders:8080/stock, gets HTTP 404 and exits with code 1 on startup, so it restarted 3 times and is 0/1 ready with Available=False. Before the change, orders-api had nothing failing. Medium confidence on the mechanism: API_VERSION is the only config diff I can see, and the link between it and the path change is inferred from the logs.
**Severity:** high  ·  **Affected:** orders/deployment/inventory, orders/deployment/orders-api

**Evidence**
- `kubernetes_pod_logs`: orders-api FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found
- `kubernetes_pod_logs`: inventory: 'inventory serving /v2/stock'
- `kubernetes_recent_changes`: inventory revision 2 rollout 48s ago, env_added API_VERSION
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 0/1, restarts 3, Error exit code 1

**Recommendations**
1. Roll back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders), which restores /stock. This is the lowest-risk fix and needs human approval.
2. Alternatively, update orders-api's INVENTORY_URL or stock path to /v2/stock, or set API_VERSION so inventory keeps the old path. Confirm the intended API contract with the inventory owners first.
3. After the fix, confirm orders-api reaches 1/1 ready with no new restarts and no new warning events.
4. Add a contract check (or a consumer integration test) between inventory and orders-api so breaking API changes are caught before rollout.

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders", "label_selector": ""}
4. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders", "warnings_only": true}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "container": "app", "tail_lines": 100, "previous": false}
7. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "container": "app", "tail_lines": 100, "previous": false}
8. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "orders-api"}
9. `incidents_search` {"keywords": "inventory orders-api stock 404", "days": 90, "limit": 5}
