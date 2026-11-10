## inventory revision 2 (adds API_VERSION) moved its stock endpoint to /v2/stock. orders-api still calls /stock, gets a 404 and exits with a fatal error, so it is in CrashLoopBackOff.

**Root cause** (high confidence, `bad_rollout`): The inventory rollout to revision 2, 48s ago, added the env var API_VERSION, and inventory now logs 'serving /v2/stock'. orders-api is unchanged and requests GET http://inventory.orders:8080/stock. That returns HTTP 404, orders-api treats it as fatal ('stock sync failed') and exits with code 1, so it has restarted 3 times and is in back-off. The Hub found nothing failing before the change.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_recent_changes`: inventory revision 2, 48s ago, added env API_VERSION. No other workload changed.
- `kubernetes_pod_logs`: orders-api: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'. inventory: 'inventory serving /v2/stock'.
- `kubernetes_describe_pod`: orders-api-568b7b8d9f-vzp22 has 3 restarts, exit code 1 and Ready=False, plus BackOff events. Its image was pulled 48s ago, the same time as the inventory rollout.
- `kubernetes_list_pods`: orders-api is 0/1 ready with 3 restarts. inventory is 1/1 ready with 0 restarts.

**Recommendations**
1. Roll inventory back to revision 1 (kubectl rollout undo deployment/inventory -n orders), or remove or fix API_VERSION so inventory serves /stock again.
2. Check that orders-api recovers (Ready 1/1, no new restarts) once inventory serves /stock.
3. Before re-applying API_VERSION, update orders-api's INVENTORY_URL or client to call /v2/stock, or have inventory keep serving the old /stock path during the migration.

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "tail_lines": 50}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 50}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
7. `incidents_search` {"keywords": "orders-api inventory stock 404"}
8. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
