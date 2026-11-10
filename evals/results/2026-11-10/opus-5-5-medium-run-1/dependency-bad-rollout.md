## orders-api-568b7b8d9f-vzp22 is crash looping (exit 1, 3 restarts). On startup it calls GET http://inventory.orders:8080/stock, gets a 404 and exits. About 48s ago the inventory deployment rolled out revision 2, which added an API_VERSION env var, and inventory now serves /v2/stock, so the /stock path orders-api uses no longer exists.

**Root cause** (high confidence, `bad_rollout`): The cause is the inventory rollout to revision 2, not orders-api itself. That revision (48s ago) added the API_VERSION env var to the app container. The new inventory pod logs 'inventory serving /v2/stock'. orders-api 2.3.0 still calls the old path at startup and gets 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found', then exits with code 1. orders-api has had no changes since it was created (revision 1).
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22: Running 0/1, 3 restarts, last terminated Error exit_code 1; inventory-b775d96fd-qq86l is 44s old and Ready
- `kubernetes_pod_logs`: orders-api (previous logs gone, latest instance shown): 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'; inventory pod: 'inventory serving /v2/stock'
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago, env_added app: [API_VERSION]; orders-api has only revision 1 (created 2m ago)

**Recommendations**
1. Roll inventory back to revision 1 (e.g. kubectl -n orders rollout undo deployment/inventory --to-revision=1), or remove the API_VERSION env var, so inventory serves /stock again.
2. Check that orders-api comes up Ready after the rollback. If it is still in CrashLoopBackOff backoff, it should recover on its next restart attempt.
3. Longer term: have inventory serve both /stock and /v2/stock during migrations, or move orders-api to /v2/stock before switching inventory over. Also consider making the orders-api startup stock sync retry instead of exiting.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 50}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 50}
