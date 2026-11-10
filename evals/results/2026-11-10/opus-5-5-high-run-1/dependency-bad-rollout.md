## orders-api-568b7b8d9f-vzp22 is crash looping (exit code 1, 3 restarts). It crashes on startup because its stock sync call to http://inventory.orders:8080/stock returns HTTP 404. Its dependency inventory was rolled out to revision 2 about 48s ago, which added API_VERSION, and inventory now logs that it serves /v2/stock.

**Root cause** (high confidence, `bad_rollout`): Inventory revision 2 (ReplicaSet inventory-b775d96fd, rolled out about 44-48s ago) added the env var API_VERSION. The new inventory pod logs "inventory serving /v2/stock", so it no longer answers on the /stock path that orders-api 2.3.0 calls. At startup orders-api runs GET http://inventory.orders:8080/stock, gets HTTP 404 Not Found, logs FATAL and exits with code 1, so Kubernetes keeps restarting it. orders-api itself has not changed: it has only revision 1, created 2m ago. Caveat: the revision 1 inventory pod is gone, so I couldn't confirm directly that it served /stock. That conclusion rests on the timing and on the path change.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 is 0/1 ready with 3 restarts; its container terminated with Error, exit code 1 (no OOM). inventory-b775d96fd-qq86l is Running 1/1, age 44s.
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22 (previous logs gone, latest instance shown): 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'.
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l logs: 'inventory serving /v2/stock', so the /stock path that orders-api calls is no longer served.
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago with env_added app: [API_VERSION]. orders-api was only created (revision 1) 2m ago, with no later change.
- `kubernetes_describe_deployment`: inventory rollout history: rev 2 (inventory-b775d96fd, 44s) has env [API_VERSION]; rev 1 (inventory-8469585669, 2m) had no env. The image is python:3.12-alpine in both.
- `kubernetes_get_events`: BackOff restarting failed container app in pod orders-api-568b7b8d9f-vzp22 (count 3, last seen 3s ago).

**Recommendations**
1. Roll back the inventory deployment to revision 1 (`kubectl -n orders rollout undo deployment/inventory --to-revision=1`), or remove the API_VERSION env var, so inventory serves /stock again. This needs approval.
2. Once inventory serves /stock again, confirm that orders-api-568b7b8d9f-vzp22 starts and becomes Ready on its next restart (no FATAL in its logs). Don't restart it as the fix; the crash comes from the inventory path change.
3. Before inventory moves to /v2/stock again, update orders-api to call /v2/stock, or have inventory serve both /stock and /v2/stock during the migration.
4. Consider making orders-api's startup stock sync retry or degrade gracefully instead of exiting fatally when it gets a dependency error.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api crash loop"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 50}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
7. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 50}
8. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders"}
