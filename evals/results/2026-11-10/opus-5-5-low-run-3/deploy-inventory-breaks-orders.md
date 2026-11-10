## orders-api is in CrashLoopBackOff because inventory's /stock endpoint now returns 404. This started right after inventory revision 2, which added the API_VERSION env var.

**Root cause** (high confidence, `bad_rollout`): Inventory revision 2 (48s ago) added the env var API_VERSION. The new inventory pod no longer serves GET /stock and returns 404 instead. On startup, orders-api 2.3.0 calls http://inventory.orders:8080/stock, gets the 404, logs FATAL and exits with code 1. It has restarted 3 times since the rollout. Nothing was failing before the change.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_recent_changes`: inventory revision 2 (48s ago) added env var API_VERSION
- `kubernetes_pod_logs`: orders-api: GET http://inventory.orders:8080/stock returned HTTP Error 404, process exits FATAL
- `kubernetes_list_pods`: orders-api is 0/1 ready with 3 restarts and exit code 1; the last two terminations were 26s and 3s ago, both after the rollout
- `kubernetes_get_events`: BackOff warnings for orders-api-568b7b8d9f-vzp22

**Recommendations**
1. Roll inventory back to revision 1 (kubectl rollout undo deployment/inventory -n orders), or remove API_VERSION or set it to a version that still serves /stock
2. Confirm that orders-api becomes ready after the rollback
3. Before redeploying the inventory API version change, coordinate it with orders-api so orders-api calls the new endpoint path

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "tail_lines": 30}
5. `incidents_search` {"keywords": "orders-api inventory"}
