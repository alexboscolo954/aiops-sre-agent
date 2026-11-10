## orders-api is crash-looping because inventory's new revision serves the stock endpoint at /v2/stock, so orders-api's call to /stock returns 404.

**Root cause** (high confidence, `bad_rollout`): inventory revision 2 (about 48s ago) added the env var API_VERSION. The inventory pod now logs 'serving /v2/stock', so the old /stock path is gone. orders-api (unchanged since revision 1) still calls http://inventory.orders:8080/stock, gets HTTP 404 and exits with code 1 at startup, so it never becomes ready.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'. inventory: 'inventory serving /v2/stock'.
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago with env_added API_VERSION. This is the only change besides the initial creation of both deployments.
- `kubernetes_describe_deployment`: inventory revision 1 had no env vars and revision 2 has API_VERSION. orders-api has only revision 1, with the env INVENTORY_URL.

**Recommendations**
1. Roll back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders), or remove the API_VERSION env var, so /stock is served again. This needs human approval.
2. Alternatively, update orders-api to call the /v2/stock endpoint (change INVENTORY_URL or its code) and roll it out.
3. Agree on an API versioning or compatibility plan between inventory and orders-api before the next inventory rollout.
4. After the fix, confirm orders-api is 1/1 ready.

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "tail_lines": 50}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "orders-api"}
7. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 30}
8. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
