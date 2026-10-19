## orders-api is crash looping because its startup stock sync calls inventory's /stock endpoint and gets HTTP 404. The inventory deployment rolled out revision 2 about 48 seconds ago (adding API_VERSION), and its logs now say it serves /v2/stock. The likely fix is to roll inventory back to revision 1 or align orders-api with the /v2 path.

**Root cause** (medium confidence, `bad_rollout`): Inventory revision 2 (rolled out ~48s before the alert) changed the API to /v2/stock, as its startup log shows. orders-api 2.3.0 still calls GET http://inventory.orders:8080/stock, gets 404, and exits at startup with FATAL, so the container restarts repeatedly. orders-api has no code or config change of its own; it fails because its dependency changed.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs (orders-api-568b7b8d9f-vzp22, previous=true)`: 'orders-api starting, version 2.3.0' followed by 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_describe_pod (orders-api-568b7b8d9f-vzp22)`: Container app terminated with Error, exit code 1, restarts 3; Ready False with ContainersNotReady; no liveness or readiness probes; memory limit 32Mi
- `kubernetes_recent_changes`: inventory revision 2 rollout 48s ago added env API_VERSION; orders-api has only revision 1, created 2m ago, with no diff
- `kubernetes_pod_logs (inventory-b775d96fd-qq86l, current)`: 'inventory serving /v2/stock'
- `kubernetes_describe_deployment (inventory)`: Revision 2 (inventory-b775d96fd) is the current ready 1/1 ReplicaSet; revision 1 (inventory-8469585669) is scaled to 0, and the deployment is Available
- `kubernetes_get_events (orders)`: Readiness probe failures on the inventory pods (connection refused) were recorded while inventory was starting; the orders-api pod had FailedScheduling events that have since cleared

**Recommendations**
1. Roll back the inventory deployment to revision 1 (kubectl rollout undo deployment/inventory -n orders), which restores /stock, then confirm orders-api starts and stays Ready. This needs human approval.
2. Alternatively, fix the mismatch on the orders-api side: point its stock sync at /v2/stock or set INVENTORY_URL to the v2 endpoint, if inventory v2 is intended to stay.
3. Confirm which inventory API version is intended before choosing between rollback and fix; the inventory team should own that decision.
4. Once orders-api is Ready, check that the crash loop alert clears and that no other consumers of inventory /stock are broken by the v2 change.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_recent_changes`
4. `kubernetes_pod_logs`
5. `kubernetes_describe_pod`
6. `kubernetes_get_events`
7. `kubernetes_describe_deployment`
8. `kubernetes_pod_logs`
