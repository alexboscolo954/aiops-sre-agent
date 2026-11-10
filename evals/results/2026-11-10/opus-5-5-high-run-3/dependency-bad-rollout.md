## orders-api is in a crash loop: 3 restarts, exit code 1, 0/1 ready. On startup it calls GET http://inventory.orders:8080/stock, gets HTTP 404 and exits. About 48s ago inventory rolled out revision 2, which added an API_VERSION env var, and it now serves only /v2/stock.

**Root cause** (high confidence, `bad_rollout`): Inventory revision 2 (ReplicaSet inventory-b775d96fd, rolled out about 48s ago) added the env var API_VERSION, and the inventory pod now logs 'inventory serving /v2/stock'. orders-api 2.3.0 still calls the old path /stock at startup ('FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found') and exits with code 1 on every start, so it crash loops. orders-api itself has only revision 1 and has not changed. One caveat: orders-api's container first started about 48s ago, at the same moment as the inventory rollout, because the image pull had been waiting. So no run against inventory revision 1 was seen. That revision 1 served /stock is inferred from the diff and the path change, not observed directly.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22: Running, 0/1 ready, 3 restarts, last terminated Error with exit code 1. inventory-b775d96fd-qq86l is healthy, 1/1 ready, 44s old.
- `kubernetes_pod_logs`: orders-api (latest instance; the previous instance's logs were gone): 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l: 'inventory serving /v2/stock'
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago with env_added API_VERSION. orders-api has only revision 1 (created 2m ago) and no changes since.
- `kubernetes_describe_deployment`: inventory history: revision 1 (inventory-8469585669) had no env vars; revision 2 (inventory-b775d96fd, 44s old) adds API_VERSION, same image python:3.12-alpine.
- `kubernetes_describe_pod`: orders-api has env INVENTORY_URL, no probes, and BackOff warning events. Its image pull finished 48s ago, so it first started when inventory revision 2 rolled out.

**Recommendations**
1. Roll back inventory to revision 1 (ReplicaSet inventory-8469585669), for example with `kubectl rollout undo deployment/inventory -n orders --to-revision=1`, or set API_VERSION so inventory serves /stock again. This needs approval.
2. Once inventory serves /stock again, check that orders-api's next start passes the stock sync. Do not restart it to fix this: a restart won't help while /stock returns 404, and CrashLoopBackOff keeps retrying anyway.
3. If the move to /v2 is intended, update orders-api's INVENTORY_URL or its client to /v2/stock before rolling inventory revision 2 forward again, or have inventory serve both paths during the migration.
4. Follow-up: make orders-api retry or degrade gracefully when the inventory stock sync fails at startup, instead of exiting fatally.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api crash loop"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 50}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
7. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 50}
8. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
