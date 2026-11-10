## orders-api-568b7b8d9f-vzp22 is crash looping (3 restarts, exit code 1). At startup it calls GET http://inventory.orders:8080/stock and gets 404 Not Found. The likely cause is the inventory rollout to revision 2 about 48s ago, which added API_VERSION and made inventory serve only /v2/stock.

**Root cause** (medium confidence, `bad_rollout`): The inventory Deployment rolled out revision 2 (ReplicaSet inventory-b775d96fd) about 48s ago. The only change from revision 1 was the new env var API_VERSION. The new inventory pod logs 'inventory serving /v2/stock'. orders-api 2.3.0 still calls the old path GET http://inventory.orders:8080/stock at startup, gets HTTP 404, logs 'FATAL: stock sync failed' and exits with code 1. Both pods sat Pending (node taint) until about 47s ago, so orders-api first ran against revision 2 and never had a successful start. One gap: I couldn't see that revision 1 served /stock. Its pod is gone and env var values are hidden. So the claim that revision 1 worked is inferred from the path mismatch, not observed.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 is Running with 0/1 ready and 3 restarts; last terminated Error, exit code 1. inventory-b775d96fd-qq86l is healthy, 1/1.
- `kubernetes_pod_logs`: orders-api (previous logs gone, so this is the latest run): 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l logs: 'inventory serving /v2/stock', so the path orders-api calls (/stock) doesn't exist anymore.
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago with env_added API_VERSION. orders-api hasn't changed since it was created (revision 1, 2m ago).
- `kubernetes_describe_deployment`: In inventory's history, revision 2 (inventory-b775d96fd, 44s) has env [API_VERSION] and revision 1 (inventory-8469585669, 2m) has no env. The image python:3.12-alpine is the same in both.
- `kubernetes_get_events`: Both pods hit FailedScheduling (untolerated taint) about 2m ago. orders-api has had BackOff 'restarting failed container app' 3 times, last seen 3s ago.

**Recommendations**
1. Roll inventory back to revision 1 (ReplicaSet inventory-8469585669, without API_VERSION) so it serves /stock again, e.g. `kubectl -n orders rollout undo deployment/inventory --to-revision=1`. This needs approval. Then check that orders-api starts and becomes Ready.
2. Or, if the move to v2 is intended, update orders-api to call /v2/stock, or have inventory serve both /stock and /v2/stock during the migration.
3. Don't restart orders-api: it will keep failing until inventory serves /stock again.
4. Follow-up: have orders-api retry the stock sync with backoff instead of exiting fatally. Coordinate inventory API version changes with its consumers.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api crash"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 50}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
7. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 50}
8. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders", "warnings_only": false}
