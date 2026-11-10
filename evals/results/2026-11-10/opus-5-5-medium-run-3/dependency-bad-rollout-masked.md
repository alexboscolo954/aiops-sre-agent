## orders-api (pod orders-api-568b7b8d9f-vzp22) is crash looping because its startup stock sync calls GET http://inventory.orders:8080/stock and gets a 404. That fits the inventory rollout to revision 2 about 48s ago, which added API_VERSION and now serves only /v2/stock.

**Root cause** (medium confidence, `bad_rollout`): inventory revision 2 (ReplicaSet inventory-b775d96fd, created about 44s ago) added the env var API_VERSION to an unchanged image, python:3.12-alpine. Its log now says 'inventory serving /v2/stock'. orders-api 2.3.0 still calls the old path, gets 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found' and exits with code 1. orders-api itself has only revision 1 and has not changed. Two things are inferred rather than seen: that inventory.orders is the inventory service, and that inventory revision 1 served /stock. The orders-api pod is 2m old with 3 restarts, so some restarts may predate inventory revision 2. Its previous-run logs were gone, so I could only read the latest crash.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 is Running but 0/1 ready, with 3 restarts; its last termination was Error, exit code 1. inventory-b775d96fd-qq86l is 1/1 and 44s old.
- `kubernetes_pod_logs`: orders-api pod (latest run; previous logs were gone): 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l log: 'inventory serving /v2/stock'
- `kubernetes_recent_changes`: inventory rolled out revision 2 48s ago, adding env API_VERSION. orders-api has only revision 1 (created 2m ago), so it has not changed.
- `kubernetes_describe_deployment`: inventory revision 2 (inventory-b775d96fd) has env [API_VERSION]; revision 1 (inventory-8469585669) had no env. Both use the same image, python:3.12-alpine.

**Recommendations**
1. Roll back inventory to revision 1 (kubectl -n orders rollout undo deployment/inventory --to-revision=1) so it serves /stock again. This needs approval.
2. Once rolled back, confirm orders-api-568b7b8d9f-vzp22 starts and becomes Ready. It should recover on its next back-off restart, so no manual restart is needed.
3. Before switching inventory to the v2 API again, update orders-api to call /v2/stock, or keep inventory serving both paths during the migration.
4. Make orders-api's startup stock sync retry or degrade gracefully instead of exiting on a dependency error.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api crash"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 50}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
7. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 50}
