## orders-api-568b7b8d9f-vzp22 is crash looping (exit 1, 3 restarts). At startup it calls GET http://inventory.orders:8080/stock and gets 404 Not Found. About 48s ago, inventory revision 2 added API_VERSION, and inventory now serves only /v2/stock, so the inventory rollout broke the API that orders-api depends on.

**Root cause** (high confidence, `bad_rollout`): Inventory revision 2 (rolled out 48s ago, ReplicaSet inventory-b775d96fd) added the env var API_VERSION. Its log now says 'inventory serving /v2/stock', so the old /stock path is gone. orders-api 2.3.0 runs a stock sync at startup against http://inventory.orders:8080/stock, gets 'HTTP Error 404: Not Found' and exits with code 1, which causes the crash loop. Two things are inferred rather than shown: that inventory.orders is the inventory service, and that orders-api only started failing after the inventory rollout. Both fit the timing and the path mismatch. Previous-instance logs were gone, so the crash output comes from the latest instance.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 is 0/1 ready with 3 restarts, terminated Error exit_code 1. inventory-b775d96fd-qq86l is running, 44s old.
- `kubernetes_pod_logs`: orders-api: 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'. Inventory pod: 'inventory serving /v2/stock'.
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago with env_added API_VERSION. orders-api has had no changes since it was created 2m ago (revision 1).
- `kubernetes_describe_deployment`: inventory rollout history: revision 1 (inventory-8469585669) had no env vars and is scaled to 0. Revision 2 (inventory-b775d96fd) adds API_VERSION and is serving.

**Recommendations**
1. Roll back inventory to revision 1 (kubectl -n orders rollout undo deployment/inventory --to-revision=1) to bring back the /stock endpoint. Alternatively, remove or correct API_VERSION so the old path is served.
2. Check that the orders-api pod passes its stock sync and becomes Ready after the rollback. Don't just restart orders-api: that won't fix the 404.
3. Confirm that inventory.orders is the inventory service.
4. Long term: coordinate the API version change. Either have inventory serve both /stock and /v2/stock during a migration, or update orders-api to call /v2/stock before inventory drops the old path. Consider having orders-api retry or degrade instead of exiting when the startup sync fails.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api crashloop"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 50}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
7. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 50}
