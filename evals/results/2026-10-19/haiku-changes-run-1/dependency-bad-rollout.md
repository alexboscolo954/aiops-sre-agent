## orders-api pod orders-api-568b7b8d9f-vzp22 is crash looping because its startup stock sync gets HTTP 404 from inventory.orders:8080/stock and exits with code 1. The inventory deployment was rolled out to revision 2 about 44 seconds before the crash began, which points to that rollout as the likely trigger. The orders-api pod is 0/1 ready, so the service is down.

**Root cause** (medium confidence, `dependency_failure`): orders-api (v2.3.0) fails at startup with 'stock sync failed: GET http://inventory.orders:8080/stock: HTTP 404'. The inventory deployment rolled out revision 2 (inventory-b775d96fd, adds env API_VERSION) about 44s before the alert, and that rollout is the only recent change in the cluster. The most likely cause is that the new inventory revision no longer serves /stock at the path orders-api calls. This is inferred from the timing and the 404, and I did not check inventory's logs or routes, so confidence is medium.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Pod/orders-api-568b7b8d9f-vzp22, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: Previous/latest orders-api logs: 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'.
- `kubernetes_describe_pod`: Container app terminated with Error, exit code 1, restarts 3; Ready=False (ContainersNotReady). No probes configured. Image python:3.12-alpine, env INVENTORY_URL.
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago, diff env_added app: [API_VERSION]; inventory revision 1 and orders-api revision 1 were created 2m ago. No other changes in the window.
- `kubernetes_describe_deployment`: inventory: 1/1 ready, Available=True, revision 2 (inventory-b775d96fd) running with 0 restarts, so the inventory rollout itself is healthy but may have changed its API surface.
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 Running but 0/1 ready, restarts 3, last terminated Error exit 1; inventory-b775d96fd-qq86l 1/1 Running, 0 restarts.

**Recommendations**
1. Check inventory's logs and its /stock route on the current revision (inventory-b775d96fd) to confirm the path changed or the endpoint is missing.
2. If confirmed, roll back the inventory deployment to revision 1 (kubectl rollout undo, or the equivalent) so orders-api can start, then fix API_VERSION or the routing before rolling forward again.
3. Alternatively, fix the orders-api INVENTORY_URL or the path it calls if the 404 comes from a contract change that is intended.
4. Do not restart orders-api alone; it will keep crash looping until the inventory endpoint responds with 200.
5. After recovery, confirm orders-api reaches 1/1 ready and the crash loop alert clears.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_describe_pod`
3. `kubernetes_pod_logs`
4. `kubernetes_recent_changes`
5. `kubernetes_describe_deployment`
6. `kubernetes_list_pods`
