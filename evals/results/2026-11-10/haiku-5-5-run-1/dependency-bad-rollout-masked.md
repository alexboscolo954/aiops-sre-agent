## orders-api pod is crash looping (3 restarts, exit 1) because its startup stock sync calls GET /stock on the inventory service and gets HTTP 404. The inventory Deployment was rolled out 48s before the alert (revision 1 -> 2, adding env API_VERSION) and its log now reads "inventory serving /v2/stock", so the likely cause is that inventory moved its endpoint from /stock to /v2/stock. Confirm with the owners of both services.

**Root cause** (medium confidence, `bad_rollout`): The inventory Deployment rolled out revision 2 about 48s before the alert, adding env API_VERSION. Its current log says "inventory serving /v2/stock". orders-api (python:3.12-alpine, image unchanged) fails at startup with "FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found" and exits with code 1. The request to /stock returns 404 because inventory now serves /v2/stock. This is a dependency mismatch caused by the inventory rollout, not an orders-api change. The orders-api deployment has only revision 1 and was created 2m ago. Its last-terminated reason is Error, not OOM. The 404 cause is inferred from the endpoint difference, not confirmed by a direct call.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Pod/orders-api-568b7b8d9f-vzp22, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22 (latest instance): 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22: ready 0/1, restarts 3, last terminated Error with exit_code 1; no OOMKilled
- `kubernetes_recent_changes`: orders/inventory revision 2 rollout 48s ago, env_added API_VERSION; orders-api has only revision 1 (created 2m ago), no rollout
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l: 'inventory serving /v2/stock'
- `kubernetes_describe_deployment`: orders-api: image python:3.12-alpine, env INVENTORY_URL only, limits 32Mi; inventory revision 2 adds API_VERSION, same image
- `kubernetes_describe_pod`: orders-api container exit 1 with no liveness/readiness probes; events show BackOff restarting failed container

**Recommendations**
1. Confirm the inventory endpoint change: check the inventory API_VERSION setting and whether /stock is still served (for example, a curl from inside the cluster to inventory:8080/stock). Check with the inventory owners whether /v2/stock is the intended path.
2. Fix the mismatch on the side that should change. Either point orders-api at /v2/stock (a config or code change in orders-api 2.3.0), or roll inventory back to revision 1 (kubectl rollout undo deployment/inventory -n orders) if the /v2 change was unintended. Choose after confirming with the owners. Do not restart orders-api alone; the crash loop will continue.
3. After the fix, confirm orders-api-568b7b8d9f-vzp22 (or its replacement) reaches 1/1 Ready and the restart count stops increasing.

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
6. `incidents_search` {"keywords": "orders-api crashloop"}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "orders-api"}
8. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l"}
9. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
10. `TriageReport` {"summary": "orders-api pod is crash looping (3 restarts, exit 1) because its startup stock sync calls GET /stock on the inventory service and gets HTTP 404. The inventory Deployment was rolled out 48s before the alert (revision 1 -> 2, adding env API_VERSION) and its log now reads \"inventory servi
11. `TriageReport` {"summary": "orders-api pod is crash looping (3 restarts, exit 1) because its startup stock sync calls GET /stock on the inventory service and gets HTTP 404. The inventory Deployment was rolled out 48s before the alert (revision 1 -> 2, adding env API_VERSION) and its log now reads \"inventory servi
