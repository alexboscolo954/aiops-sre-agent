## orders-api cannot become ready because its startup stock sync calls inventory /stock and gets 404. Inventory revision 2 (rolled out ~48s ago, adds API_VERSION) now serves /v2/stock. Rolling inventory back to revision 1 or aligning orders-api's inventory path should restore readiness.

**Root cause** (medium confidence, `bad_rollout`): inventory revision 2 (rolled out 48s before the check, adding env API_VERSION) serves /v2/stock, while orders-api 2.3.0 requests http://inventory.orders:8080/stock. The request gets HTTP 404, orders-api exits with code 1 at startup, and it restarts repeatedly (3 restarts, CrashLoopBackOff). Inferred: API_VERSION switched inventory to a versioned path; the logs show the path change but not the env-to-path link directly.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found (orders-api-568b7b8d9f-vzp22)
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l: 'inventory serving /v2/stock'
- `kubernetes_recent_changes`: inventory revision 2 rollout 48s ago, env_added API_VERSION
- `kubernetes_describe_deployment`: inventory revision 1 (inventory-8469585669) at 0 replicas, available for rollback

**Recommendations**
1. Roll back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders), which is the known-good revision, so orders-api's /stock calls succeed again. This needs human approval.
2. Alternatively, have the inventory owners confirm whether /v2/stock is intended, and if so update orders-api's inventory URL/version to match, or drop API_VERSION from inventory.
3. After the fix, confirm orders-api pod reaches 1/1 Ready and the deployment shows 1/1 available.
4. Ask the inventory team to add a compatibility route for /stock or a versioned client contract before the next inventory rollout.

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders", "label_selector": "app=orders-api"}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "container": "app", "tail_lines": 100, "previous": false}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
6. `incidents_search` {"keywords": "orders-api inventory stock 404", "days": 90, "limit": 5}
7. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "container": "app", "tail_lines": 100, "previous": false}
8. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
