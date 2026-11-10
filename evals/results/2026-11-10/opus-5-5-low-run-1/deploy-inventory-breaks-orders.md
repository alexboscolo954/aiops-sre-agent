## orders-api is crash-looping because inventory revision 2 no longer serves /stock (it returns 404). That revision added the API_VERSION env var.

**Root cause** (high confidence, `bad_rollout`): inventory revision 2, rolled out 48s ago, added the env var API_VERSION. Since then, GET /stock on inventory.orders:8080 returns 404 Not Found. orders-api 2.3.0 runs a stock sync on startup, so it hits the 404, exits with code 1 and goes into CrashLoopBackOff. Before the change, nothing in the namespace was failing. The env var most likely changed inventory's API path or version, but I couldn't see its value, so that part is inferred.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_recent_changes`: inventory moved to revision 2 48s ago, and the only change was adding the env var API_VERSION.
- `kubernetes_pod_logs`: orders-api logs: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_list_pods`: orders-api pod is 0/1 Ready with 3 restarts and exit code 1; its last crashes were after the rollout.
- `kubernetes_get_events`: orders-api has a BackOff warning, last seen 3s ago.

**Recommendations**
1. Roll inventory back to revision 1 (kubectl rollout undo deployment/inventory -n orders), or remove or correct API_VERSION.
2. Confirm that orders-api becomes Ready once /stock returns 200 again.
3. Agree the inventory API version with orders-api before rolling out again.

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "tail_lines": 30}
5. `incidents_search` {"keywords": "orders-api inventory"}
