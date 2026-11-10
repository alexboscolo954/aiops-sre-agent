## orders-api has 0/1 replicas ready and its pod is crash looping. On startup it syncs stock from inventory at /stock and gets 404. About 48s ago inventory rolled out revision 2, which serves /v2/stock.

**Root cause** (high confidence, `bad_rollout`): Inventory rolled out revision 2 (ReplicaSet inventory-b775d96fd, about 48s ago). The only change was a new env var, API_VERSION. The new inventory pod logs 'inventory serving /v2/stock'. orders-api 2.3.0 still calls GET http://inventory.orders:8080/stock at startup, gets 'HTTP Error 404: Not Found' and exits with code 1 (FATAL: stock sync failed). That leaves it in CrashLoopBackOff with 0/1 ready. Revision 1 of inventory had no API_VERSION env. The earlier FailedScheduling events from a node taint are from about 2m ago and cleared up; the pod is scheduled now.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22: 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found' (this is the latest run; the previous run's logs are gone)
- `kubernetes_recent_changes`: 48s ago inventory rolled out revision 2 with env_added API_VERSION; orders-api has not changed since it was created
- `kubernetes_describe_deployment`: inventory revision 2 (inventory-b775d96fd) has env API_VERSION; revision 1 (inventory-8469585669, now 0 replicas) had no env
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l: 'inventory serving /v2/stock'
- `kubernetes_describe_pod`: orders-api pod app container terminated Error exit_code 1, 3 restarts, BackOff events, no readiness or liveness probe, env INVENTORY_URL
- `kubernetes_get_events`: BackOff restarting failed container app in pod orders-api-568b7b8d9f-vzp22 (count 3, last seen 3s)

**Recommendations**
1. Roll inventory back to revision 1 (kubectl rollout undo deployment/inventory -n orders), or remove API_VERSION so it serves /stock again. Then confirm orders-api becomes 1/1 ready.
2. Or, if the move to v2 is intended, point orders-api's INVENTORY_URL / stock path at /v2/stock and roll orders-api out.
3. Make inventory keep serving the old /stock path during API version changes, or roll its consumers out together with it.

Runbook: `deployment-unavailable`

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true}
6. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
7. `incidents_search` {"keywords": "orders-api"}
8. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l"}
9. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
10. `runbooks_search_runbooks` {"keywords": "crashloop dependency rollback"}
11. `runbooks_read_runbook` {"name": "deployment-unavailable"}
