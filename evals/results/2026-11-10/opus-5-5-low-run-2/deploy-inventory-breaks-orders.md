## orders-api started crash-looping right after inventory revision 2 rolled out. It gets 404 from inventory's /stock endpoint at startup.

**Root cause** (high confidence, `bad_rollout`): Inventory revision 2 added the env var API_VERSION, which apparently changes its API so that GET /stock now returns 404. orders-api 2.3.0 calls http://inventory.orders:8080/stock when it starts, gets the 404, exits with code 1 and crash-loops. The timing fits: orders-api has not changed itself, the Hub saw nothing failing just before the change, and the failures started after the rollout 48s ago.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_recent_changes`: inventory revision 2, 48s ago: added env var API_VERSION.
- `kubernetes_pod_logs`: orders-api: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_list_pods`: orders-api pod is 0/1 ready with 3 restarts and exit code 1.
- `kubernetes_get_events`: BackOff restarting failed container app in orders-api, x3.

**Recommendations**
1. Roll back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders), or remove or correct API_VERSION so the /stock path works again.
2. Check that orders-api comes back ready once /stock responds.
3. Before rolling out again, agree on the API version change with the orders-api owners.

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "tail_lines": 40}
5. `incidents_search` {"keywords": "orders-api inventory API_VERSION"}
