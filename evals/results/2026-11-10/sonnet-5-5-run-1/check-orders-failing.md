## orders-api is crash-looping (0/1 ready). It calls inventory at /stock. The inventory rollout (revision 2, which added API_VERSION) moved the endpoint to /v2/stock, so the call returns 404.

**Root cause** (high confidence, `bad_rollout`): inventory revision 2 added env API_VERSION and now logs 'inventory serving /v2/stock'. orders-api, unchanged since revision 1, still requests http://inventory.orders:8080/stock and gets HTTP 404. It exits with code 1 at startup, so the pod never becomes ready. The inventory rollout broke the dependent workload.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_pod_logs`: inventory pod logs: 'inventory serving /v2/stock'
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago with env_added API_VERSION. orders-api was last changed at creation.
- `kubernetes_describe_deployment`: orders-api has only revision 1, with env INVENTORY_URL. inventory revision 2 has API_VERSION and revision 1 had no env.

**Recommendations**
1. Roll back inventory to revision 1, or remove the API_VERSION env var, so /stock is served again. Then confirm orders-api becomes ready.
2. Alternatively, update orders-api to call /v2/stock, for example by changing the path in its INVENTORY_URL or code.
3. Keep the old /stock path available, or version the API, so a change to inventory does not break its clients.

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "tail_lines": 50}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "orders-api"}
7. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 30}
8. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
