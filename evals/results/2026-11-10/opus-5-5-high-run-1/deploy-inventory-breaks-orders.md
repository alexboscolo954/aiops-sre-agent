## orders-api is crash-looping (0/1 ready, 3 restarts) because the inventory revision 2 rollout made inventory serve /v2/stock. orders-api still calls /stock, gets HTTP 404 and exits.

**Root cause** (high confidence, `bad_rollout`): The inventory revision 2 rollout (48s ago) added the env var API_VERSION, and the new inventory pod now logs 'inventory serving /v2/stock'. orders-api 2.3.0 calls GET http://inventory.orders:8080/stock at startup, gets HTTP 404 Not Found, logs 'FATAL: stock sync failed' and exits with code 1, which puts it in CrashLoopBackOff. Revision 1 of inventory had no API_VERSION, and the Hub found nothing failing before the change. That points to API_VERSION switching the stock path from /stock to /v2/stock, which breaks orders-api.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_recent_changes`: inventory revision 2, 48s ago: env_added app: [API_VERSION].
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'.
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l: 'inventory serving /v2/stock'.
- `kubernetes_describe_pod`: orders-api-568b7b8d9f-vzp22: Ready False, 3 restarts, terminated Error with exit code 1. Its image was pulled 48s ago, when the inventory rollout happened, and it has been backing off since.
- `kubernetes_describe_deployment`: inventory revision 1 had no env vars; revision 2 (inventory-b775d96fd) has API_VERSION and is the active ReplicaSet.
- `kubernetes_get_events`: Warning BackOff on orders-api-568b7b8d9f-vzp22, count 3.

**Recommendations**
1. Roll inventory back to revision 1 (kubectl -n orders rollout undo deployment/inventory --to-revision=1), or remove or correct API_VERSION, so that inventory serves /stock again.
2. Check that orders-api recovers: its pod should become 1/1 ready and stop restarting, and its logs should no longer show the 404.
3. Before setting API_VERSION again, update orders-api to call /v2/stock, or keep /stock working in inventory, then roll out inventory again.

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
4. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "tail_lines": 50}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 50}
7. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
8. `incidents_search` {"keywords": "orders-api inventory stock 404"}
9. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
