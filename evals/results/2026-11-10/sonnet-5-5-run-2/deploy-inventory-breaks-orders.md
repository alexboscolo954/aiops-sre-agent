## After the inventory revision 2 rollout, inventory serves /v2/stock, so orders-api's call to /stock gets a 404. The orders-api container exits with code 1 and is in BackOff, with the deployment at 0/1.

**Root cause** (medium confidence, `bad_rollout`): Inventory revision 2 added env API_VERSION, and the service now serves /v2/stock (log: 'inventory serving /v2/stock'). The unchanged orders-api 2.3.0 still requests http://inventory.orders:8080/stock, gets HTTP 404, and exits with FATAL 'stock sync failed'. The orders-api pod has restarted 3 times. The rollout was 48s ago and the pod is 2m old, so some restarts may predate it. The 404 is caused by the inventory change, since revision 1 had no API_VERSION env and the failure is a 404 from the path the new revision no longer serves.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'. inventory: 'inventory serving /v2/stock'.
- `kubernetes_recent_changes`: inventory revision 2 added env API_VERSION 48s ago. orders-api was not changed.
- `kubernetes_list_deployments`: orders-api is 0/1 with Available=False (MinimumReplicasUnavailable). inventory is 1/1.

**Recommendations**
1. Roll back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders), or set API_VERSION so that the legacy /stock path is served again.
2. Alternatively, update orders-api to call /v2/stock, then redeploy it.
3. Add backward-compatible routing or a contract check before changing inventory's API path.
4. After the fix, confirm orders-api becomes 1/1 Ready and stops restarting.

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
6. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
