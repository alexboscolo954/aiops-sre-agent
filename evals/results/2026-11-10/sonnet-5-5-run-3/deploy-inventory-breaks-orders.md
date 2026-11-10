## The inventory revision 2 rollout moved the stock endpoint to /v2/stock. orders-api still calls /stock, gets a 404 and crash-loops.

**Root cause** (medium confidence, `bad_rollout`): inventory revision 2 added API_VERSION and now serves only /v2/stock, as its log shows. orders-api (version 2.3.0) calls http://inventory.orders:8080/stock at startup and exits 1 on the 404. The failure is caused by the rollout of a dependency. The Hub saw nothing failing before the change. The earlier inventory pod was unschedulable for a time due to a taint, so orders-api could not have reached /stock before the rollout either; the evidence does not show whether it would have worked once inventory revision 1 was running.
**Severity:** high  ·  **Affected:** orders/Deployment/inventory, orders/Deployment/orders-api

**Evidence**
- `kubernetes_pod_logs`: orders-api: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'. inventory: 'inventory serving /v2/stock'.
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago and added env var API_VERSION.
- `kubernetes_list_pods`: orders-api is 0/1 with 3 restarts, last exit Error code 1.

**Recommendations**
1. Roll back inventory to revision 1, or make it also serve /stock, so orders-api stops getting a 404.
2. Alternatively, update orders-api to call /v2/stock and redeploy it.
3. Add a compatibility check or contract test between inventory and orders-api before future API version changes.
4. Check that orders-api recovers and its restarts stop after the fix.

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l"}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
