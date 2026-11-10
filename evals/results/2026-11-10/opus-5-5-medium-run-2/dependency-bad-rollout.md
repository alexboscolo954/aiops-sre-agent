## orders-api-568b7b8d9f-vzp22 is crash looping (exit 1, 3 restarts). At startup it calls GET http://inventory.orders:8080/stock and gets a 404. The inventory deployment was rolled out to revision 2 (it added the API_VERSION env var) about 48s ago, and inventory now logs that it serves /v2/stock.

**Root cause** (high confidence, `bad_rollout`): orders-api runs a stock sync at startup and exits when it fails: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'. inventory revision 2, rolled out about 48s ago, added the env var API_VERSION, and the new inventory pod logs 'inventory serving /v2/stock'. So the old /stock path that orders-api calls now returns 404, and orders-api exits with code 1 on every start. No orders-api change was made: it is still on revision 1, created 2m ago. One caveat on timing: the orders-api pod is 2m old with 3 restarts, so some crashes may have happened before inventory revision 2. I only saw the log from the latest run (the previous run's logs were gone), so I can't confirm why any earlier crash happened.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 is 0/1 ready with 3 restarts, last terminated Error exit_code 1. inventory-b775d96fd-qq86l is Running and 1/1, age 44s.
- `kubernetes_pod_logs`: orders-api (latest run, because the previous run's logs were gone): 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l: 'inventory serving /v2/stock'
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago with env_added app: [API_VERSION]. orders-api is unchanged since it was created at revision 1, 2m ago.

**Recommendations**
1. Roll back the inventory deployment to revision 1 (kubectl rollout undo deployment/inventory -n orders --to-revision=1) so it serves /stock again, or remove the API_VERSION env var that revision 2 added.
2. Check that orders-api starts cleanly after the rollback. Its crash-loop backoff may delay the next restart.
3. Agree on the API change between the inventory and orders-api owners. Either inventory keeps serving /stock alongside /v2/stock, or orders-api is updated to call /v2/stock before inventory switches.
4. Optionally, make the orders-api startup stock sync retry or degrade gracefully instead of exiting with FATAL.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api crash"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 50}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 50}
