## orders-api is crash looping because its startup stock sync gets HTTP 404 from inventory /stock. inventory was rolled out to revision 2, which added the API_VERSION env var, about 48s ago.

**Root cause** (medium confidence, `bad_rollout`): inventory revision 2 (rolled out about 48s ago, adding env var API_VERSION) appears to have changed its API so GET http://inventory.orders:8080/stock now returns 404. orders-api 2.3.0 treats this as fatal at startup (exit code 1, 3 restarts). The timing and the 404 point to the inventory rollout, but I couldn't see the env value itself, so this is an inference.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_list_pods`: orders-api pod 0/1 ready, 3 restarts, exit code 1; inventory pod running since 44s
- `kubernetes_recent_changes`: inventory rollout to revision 2 48s ago added env var API_VERSION; orders-api has had no rollout since it was created

**Recommendations**
1. Roll back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders), or remove or correct API_VERSION so /stock is served again.
2. Check that GET inventory.orders:8080/stock returns 200, then confirm orders-api becomes Ready.
3. Agree on the API version between inventory and orders-api before rolling out again.

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 50}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api"}
