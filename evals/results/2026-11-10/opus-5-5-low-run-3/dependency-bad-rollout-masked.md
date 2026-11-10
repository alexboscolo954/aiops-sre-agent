## orders-api is crash looping (exit 1) because its startup stock sync gets HTTP 404 from the inventory service's /stock endpoint. This began right after inventory rolled out revision 2 about 48s ago, which added an API_VERSION env var.

**Root cause** (medium confidence, `bad_rollout`): inventory revision 2, rolled out 48s ago, added the env var API_VERSION. orders-api 2.3.0 now stops at startup with 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'. The likely cause is that the new API_VERSION setting moved or removed the /stock path, so the dependency's contract broke. I can't see env values, and I didn't confirm that inventory.orders is the inventory service, so this is inferred from the timing and the error.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_describe_pod`: Container app exited with code 1 (Error), 3 restarts, BackOff events; env INVENTORY_URL
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago, env_added API_VERSION; orders-api has had no rollouts since it was created

**Recommendations**
1. Roll back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders), or remove or correct API_VERSION.
2. Check that GET /stock on inventory returns 200 again, then confirm the orders-api pods become Ready.
3. If the inventory API change was intended, update orders-api to call the new path before rolling it out again.
4. Consider making orders-api retry or degrade on a failed stock sync instead of exiting fatally.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 50}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api crashloop"}
