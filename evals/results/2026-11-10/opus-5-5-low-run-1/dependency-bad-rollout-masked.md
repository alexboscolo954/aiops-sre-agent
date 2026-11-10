## orders-api is crash looping (exit 1, 3 restarts) because its startup stock sync gets HTTP 404 from inventory's /stock endpoint. This began right after inventory rollout revision 2 (48s ago), which added the API_VERSION env var.

**Root cause** (medium confidence, `bad_rollout`): inventory revision 2 (rolled out 48s ago, added env var API_VERSION) most likely changed the API it serves, so /stock is gone. orders-api 2.3.0 calls GET http://inventory.orders:8080/stock at startup, gets 'HTTP Error 404: Not Found', and exits with a FATAL error. Two things are inferred, not shown: that inventory.orders is the inventory service, and what API_VERSION's value is (env values are hidden). I also don't know whether orders-api had started successfully before that rollout.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_describe_pod`: Container app terminated with Error, exit code 1, 3 restarts, BackOff events; env INVENTORY_URL
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago, adding env API_VERSION; orders-api has had no rollout since it was created

**Recommendations**
1. Roll back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders), or remove or correct API_VERSION so /stock is served again
2. Confirm that INVENTORY_URL / inventory.orders points at the inventory service and that GET /stock returns 200
3. After that, check that orders-api pods start and become Ready
4. Long term: version the inventory API in a backward-compatible way, and have orders-api retry instead of exiting on a failed sync

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 50}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api crash"}
