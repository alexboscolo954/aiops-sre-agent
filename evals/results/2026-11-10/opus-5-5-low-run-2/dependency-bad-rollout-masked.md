## orders-api is crash looping (exit 1, 3 restarts). At startup it calls inventory's /stock endpoint, gets HTTP 404 and exits. The 404 started right after inventory rolled out revision 2, which added an API_VERSION env var, 48s ago.

**Root cause** (medium confidence, `bad_rollout`): orders-api runs a stock sync on startup against INVENTORY_URL (GET http://inventory.orders:8080/stock). It gets 'HTTP Error 404: Not Found' and exits FATAL with code 1. inventory rolled out revision 2 about 48s ago, and the only change was a new env var, API_VERSION. That most likely moved or renamed the /stock route. This is inferred from the timing: I did not read inventory's logs or the value of API_VERSION.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_describe_pod`: Container app terminated with Error, exit_code 1, 3 restarts, BackOff events; it has env INVENTORY_URL
- `kubernetes_recent_changes`: inventory rollout to revision 2 48s ago added env API_VERSION; orders-api has not changed since it was created

**Recommendations**
1. Roll back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders), or remove API_VERSION. Either should bring back /stock.
2. Check that GET /stock on inventory returns 200 and that orders-api pods become Ready.
3. If the API version change is intended, update orders-api's INVENTORY_URL or path to match the new version, then roll inventory forward again.
4. Consider making orders-api retry or degrade gracefully when stock sync fails, instead of exiting.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 50}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api crash"}
