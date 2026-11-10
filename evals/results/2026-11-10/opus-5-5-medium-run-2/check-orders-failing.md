## orders-api is crash looping on startup (0/1 ready). It exits because GET http://inventory.orders:8080/stock returns 404. About 48s ago, inventory revision 2 added the API_VERSION env var, and inventory now says it serves /v2/stock.

**Root cause** (high confidence, `bad_rollout`): inventory revision 2 (rolled out about 48s ago, its only change the new env var API_VERSION) moved its endpoint: the new pod logs 'inventory serving /v2/stock'. orders-api 2.3.0 still calls the old path /stock at startup, gets HTTP 404, logs 'FATAL: stock sync failed' and exits with code 1. That puts it in a crash loop. orders-api itself has not changed since it was created (revision 1).
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22: 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago, adding env API_VERSION; orders-api has only revision 1 (created 2m ago)
- `kubernetes_describe_deployment`: inventory rev 2 (inventory-b775d96fd) has env API_VERSION; rev 1 (inventory-8469585669) had no env vars and is scaled to 0
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l: 'inventory serving /v2/stock'
- `kubernetes_list_pods`: orders-api pod has 3 restarts, terminated Error with exit code 1

**Recommendations**
1. Roll back inventory to revision 1 (kubectl -n orders rollout undo deployment/inventory --to-revision=1), or remove or correct the API_VERSION env var, so that /stock is served again.
2. Once inventory serves /stock, check that orders-api comes up ready (its pod will recover on its next crash-loop restart, or you can delete the pod to restart it straight away).
3. Longer term: coordinate the inventory API version change with orders-api, either by moving orders-api to /v2/stock or by having inventory serve both paths during the migration.

Runbook: `deployment-unavailable`

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 50}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 50}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
8. `runbooks_search_runbooks` {"keywords": "crashloop dependency rollback"}
9. `runbooks_read_runbook` {"name": "deployment-unavailable"}
