## orders-api is crash looping because its startup stock sync calls inventory's /stock endpoint and gets HTTP 404. The inventory deployment rolled out revision 2 about 48s before the alert, which added API_VERSION and now serves /v2/stock. The likely fix is to roll inventory back to revision 1 or realign orders-api's path with the new API.

**Root cause** (medium confidence, `bad_rollout`): Inventory revision 2 (replicaset inventory-b775d96fd) changed the API to /v2/stock, adding the API_VERSION env var. orders-api (revision 1, unchanged) still calls GET http://inventory.orders:8080/stock on startup. It gets a 404, its stock sync fails fatally, and the container exits with code 1 on each start, so Kubernetes backs off the restarts.
**Severity:** high  ·  **Affected:** orders/Pod/orders-api-568b7b8d9f-vzp22, orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs (orders-api, previous=true)`: 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 is 0/1 ready with 3 restarts; last terminated reason Error, exit code 1, not OOMKilled
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s before the alert, with env_added API_VERSION; orders-api has only its revision 1 (created 2m ago)
- `kubernetes_pod_logs (inventory-b775d96fd-qq86l)`: 'inventory serving /v2/stock', so the inventory service now serves the v2 path
- `kubernetes_describe_deployment (inventory)`: Revision 2 env: API_VERSION; revision 1 env was empty. Image is unchanged (python:3.12-alpine), so the change is config-only
- `kubernetes_get_events`: inventory readiness probe failures were connection refused during the rollout, now resolved (inventory is 1/1 ready)

**Recommendations**
1. Roll back the inventory deployment to revision 1 (kubectl rollout undo deployment/inventory -n orders), which needs human approval, then confirm orders-api starts and becomes ready.
2. Alternatively, fix orders-api's inventory URL or path to use /v2/stock, or set API_VERSION so the v1 path is served, and redeploy orders-api. Check which API version orders-api 2.3.0 expects first.
3. Do not just restart orders-api; the crash is deterministic on startup.
4. After recovery, add a contract test or staging check that orders-api can reach inventory's stock endpoint before inventory rollouts.

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
