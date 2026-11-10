## orders-api crash-loops (exit 1, 3 restarts) because its startup stock sync gets HTTP 404 from inventory. About 48s ago, inventory revision 2 added the API_VERSION env var, and inventory now serves only /v2/stock. orders-api still calls /stock.

**Root cause** (high confidence, `bad_rollout`): Inventory revision 2 (ReplicaSet inventory-b775d96fd, rolled out about 44–48s ago) added the API_VERSION env var. The new inventory pod logs 'inventory serving /v2/stock', so the path orders-api 2.3.0 calls on startup (GET http://inventory.orders:8080/stock) now returns 404. orders-api treats that as fatal ('FATAL: stock sync failed ... HTTP Error 404') and exits with code 1. The two deployments now disagree on the API path. One timing gap: the previous crash's logs are gone, so I can't confirm that every one of the 3 restarts came after the inventory rollout. Before revision 2, inventory had no API_VERSION set, so revision 1 most likely still served /stock.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 is 0/1 ready with 3 restarts, last terminated Error exit_code 1. The inventory pod is 44s old and running.
- `kubernetes_pod_logs`: orders-api logs: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'. Inventory pod logs: 'inventory serving /v2/stock'.
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago with env_added API_VERSION. orders-api itself is unchanged since it was created (revision 1).
- `kubernetes_describe_deployment`: In inventory's history, revision 2 (created 44s ago) has env [API_VERSION] and revision 1 had no env. The image (python:3.12-alpine) is the same in both.

**Recommendations**
1. Roll back inventory to revision 1 (kubectl -n orders rollout undo deployment/inventory --to-revision=1) or remove API_VERSION so /stock is served again. orders-api should recover on its next restart.
2. Confirm that orders-api becomes Ready and stops restarting.
3. Before re-applying the inventory v2 API, either update orders-api to call /v2/stock or keep /stock in inventory as a compatibility route. Roll out the two changes in a coordinated order.
4. Consider making orders-api's startup stock sync retry or degrade gracefully instead of exiting fatally.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 50}
4. `kubernetes_recent_changes` {"cluster": "kind"}
5. `incidents_search` {"keywords": "orders-api crashloop"}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 50}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
