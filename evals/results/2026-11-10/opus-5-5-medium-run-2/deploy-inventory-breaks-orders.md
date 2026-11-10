## orders-api is crash looping because inventory revision 2 moved its stock endpoint from /stock to /v2/stock. orders-api still calls /stock, gets 404, and exits at startup.

**Root cause** (high confidence, `bad_rollout`): inventory revision 2 (48s ago) added the env var API_VERSION. inventory now logs 'inventory serving /v2/stock'. orders-api 2.3.0 calls GET http://inventory.orders:8080/stock at startup, gets HTTP 404 and exits with code 1 (FATAL: stock sync failed). It has restarted 3 times since the rollout. The Hub saw nothing failing before the change.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_recent_changes`: inventory rev 2, 48s ago: env_added app: [API_VERSION]
- `kubernetes_pod_logs`: orders-api: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'. inventory: 'inventory serving /v2/stock'
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 0/1 ready, 3 restarts, Error exit 1
- `kubernetes_get_events`: BackOff restarting failed container app in pod orders-api-568b7b8d9f-vzp22 (x3)
- `kubernetes_describe_deployment`: inventory revision 1 had no env vars; revision 2 adds API_VERSION

**Recommendations**
1. Roll back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders), or remove API_VERSION, so the service serves /stock again. Needs approval.
2. Confirm that orders-api becomes Ready and stops restarting.
3. Before reapplying API_VERSION, update orders-api to call /v2/stock, or have inventory serve both /stock and /v2/stock.

Runbook: `pod-crashlooping`

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "tail_lines": 50}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 50}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
7. `incidents_search` {"keywords": "orders-api inventory stock 404"}
8. `runbooks_search_runbooks` {"keywords": "crashloop dependency rollback"}
