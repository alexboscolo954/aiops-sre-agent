## orders-api is crash-looping at startup because its stock sync calls inventory /stock, and inventory's revision 2 rollout moved that endpoint to /v2/stock, so the call returns 404. Rolling inventory back to revision 1, or otherwise restoring /stock, should let orders-api start.

**Root cause** (high confidence, `bad_rollout`): inventory revision 2 (rolled out about 48s before the check, adding env API_VERSION) serves /v2/stock. orders-api 2.3.0 still calls http://inventory.orders:8080/stock at startup, gets HTTP 404, exits with code 1, and restarts (3 restarts, BackOff). The orders-api deployment itself has not changed since revision 1.
**Severity:** high  ·  **Affected:** orders/deployment/orders-api, orders/deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found (orders-api).
- `kubernetes_pod_logs`: inventory serving /v2/stock (inventory-b775d96fd-qq86l).
- `kubernetes_recent_changes`: inventory revision 2 rollout at 48s with env_added API_VERSION; no change to orders-api since its creation.

**Recommendations**
1. Propose rolling back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders). This needs human approval and is low risk because revision 1 served /stock and ran healthily before the change.
2. Alternatively, have the inventory team confirm whether /v2/stock is intended. If so, point orders-api at /v2/stock or ship a compatible orders-api build. Do not leave inventory serving only /v2/stock while orders-api calls /stock.
3. After the fix, confirm orders-api reaches 1/1 ready and the orders-ready Check passes.

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders", "label_selector": ""}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders", "warnings_only": true}
5. `incidents_search` {"keywords": "orders-api", "days": 90, "limit": 5}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "container": "app", "tail_lines": 50, "previous": true}
7. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
8. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
9. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "container": "app", "tail_lines": 50, "previous": false}
