## orders-api is crash-looping because it calls inventory's /stock endpoint and gets a 404. The inventory rollout (revision 2) now serves /v2/stock.

**Root cause** (medium confidence, `bad_rollout`): The inventory deployment rolled out revision 2 about 48s ago and added the env var API_VERSION. Its log then read 'inventory serving /v2/stock', so the old /stock path no longer exists. orders-api (unchanged, revision 1) calls http://inventory.orders:8080/stock at startup, gets a 404, logs 'FATAL: stock sync failed' and exits 1. The cause is the rollout of inventory, which orders-api depends on. Inference: revision 1 probably served /stock, since the 404 only appeared after revision 2. I did not see revision 1's logs, and orders-api's first start was concurrent with the rollout.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404'
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago and added the env var API_VERSION

**Recommendations**
1. Roll back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders), or remove API_VERSION, so that /stock is served again.
2. Alternatively, point orders-api at the /v2/stock path, for example via INVENTORY_URL or a code change, if v2 is the intended API.
3. Make the inventory API change backward compatible, or coordinate the two rollouts, so that dependents don't break.
4. After the fix, confirm orders-api reaches 1/1 ready.

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "tail_lines": 50}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "orders-api"}
7. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 30}
8. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
