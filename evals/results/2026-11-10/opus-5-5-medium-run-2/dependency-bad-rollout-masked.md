## orders-api-568b7b8d9f-vzp22 is crash looping (exit 1, 3 restarts). At startup it calls GET http://inventory.orders:8080/stock, gets HTTP 404 and exits. About 48s before that, inventory rolled out revision 2 (added env API_VERSION), and the new inventory pod logs 'inventory serving /v2/stock', so the old /stock path no longer exists.

**Root cause** (high confidence, `bad_rollout`): Inventory revision 2 (rolled out 48s ago, adding env var API_VERSION) moved its stock endpoint to /v2/stock. orders-api 2.3.0 still calls GET http://inventory.orders:8080/stock during its startup stock sync. That call gets 404 Not Found, the app logs FATAL and exits with code 1, so the pod goes into CrashLoopBackOff. orders-api itself has not changed: it is still on revision 1, created 2m ago. Two caveats: I am assuming inventory.orders is the inventory service (its name is masked), and the crashed instance's logs were gone, so the 404 comes from the latest instance's logs.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 is 0/1 ready with 3 restarts; last terminated: Error, exit code 1. inventory-b775d96fd-qq86l was started 44s ago.
- `kubernetes_pod_logs`: orders-api (latest instance, previous logs gone): 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l: 'inventory serving /v2/stock'
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago with env_added API_VERSION; orders-api is only at revision 1 (created 2m ago)
- `kubernetes_get_events`: BackOff restarting failed container app in pod orders-api-568b7b8d9f-vzp22 (count 3, last seen 3s ago)

**Recommendations**
1. Roll inventory back to revision 1 (kubectl rollout undo deployment/inventory -n orders), or remove or adjust API_VERSION so inventory serves /stock again.
2. Check that orders-api recovers after the rollback. Restarting orders-api alone won't fix it while inventory still returns 404 on /stock.
3. Before moving inventory to /v2 again, update orders-api to call /v2/stock, or have inventory serve both /stock and /v2/stock during the migration.
4. Consider making the orders-api startup stock sync retry or degrade gracefully instead of exiting with FATAL.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 50}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 50}
7. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders", "warnings_only": false}
