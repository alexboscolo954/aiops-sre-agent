## orders-api pod orders-api-568b7b8d9f-vzp22 is crash looping because its startup stock sync calls http://inventory.orders:8080/stock and gets a 404. The inventory deployment rolled out revision 2 about 44 seconds ago, which added API_VERSION and now serves /v2/stock instead of /stock. The inventory rollout is the likely trigger.

**Root cause** (medium confidence, `bad_rollout`): Inventory revision 2 (ReplicaSet inventory-b775d96fd, adds env API_VERSION) changed the API surface to /v2/stock. orders-api 2.3.0 still requests /stock on startup, gets HTTP 404, and exits with code 1 on the fatal stock sync, so the container restarts in a loop.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Pod/orders-api-568b7b8d9f-vzp22, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api previous/latest run log: "orders-api starting, version 2.3.0" then "FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found".
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 is 0/1 Ready with restarts=3, last terminated Error exit_code 1, age 2m.
- `kubernetes_recent_changes`: inventory revision 2 rollout 48s ago with env_added API_VERSION; orders-api revision 1 created 2m ago; no other changes in orders namespace.
- `kubernetes_describe_deployment`: inventory revision 2 (replicaset inventory-b775d96fd) is the current, available revision with env API_VERSION; revision 1 (inventory-8469585669) is scaled to 0 replicas.
- `kubernetes_pod_logs`: inventory pod inventory-b775d96fd-qq86l logs: "inventory serving /v2/stock", which shows the new endpoint path, so /stock no longer exists.
- `kubernetes_describe_pod`: orders-api container has env INVENTORY_URL, with no probes and a 32Mi memory limit; the pod events show no OOMKilled reason, only exit code 1.

**Recommendations**
1. Roll back the inventory deployment to revision 1 (kubectl -n orders rollout undo deployment/inventory). This needs human approval and is the fastest fix, since orders-api then gets /stock back.
2. Alternatively, if revision 2 must stay, point orders-api at /v2/stock (or set API_VERSION so inventory keeps serving /stock) and roll out a fixed orders-api. Check that the API_VERSION setting is what moved the path.
3. After the fix, confirm orders-api-568b7b8d9f-vzp22 (or its replacement) reaches 1/1 Ready and the restart count stops rising.
4. Confirm the inventory change was intended and check which consumers call inventory /stock, since other clients may break the same way.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_recent_changes`
4. `kubernetes_pod_logs`
5. `kubernetes_describe_pod`
6. `kubernetes_describe_deployment`
7. `kubernetes_pod_logs`
