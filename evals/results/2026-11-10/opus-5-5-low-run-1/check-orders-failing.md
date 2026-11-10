## orders-api is not ready and crash-loops (3 restarts, exit code 1). At startup its stock sync to inventory gets HTTP 404. This began right after inventory rolled out revision 2, which added the API_VERSION env var.

**Root cause** (medium confidence, `bad_rollout`): inventory revision 2, rolled out 48s ago, added the env var API_VERSION. This most likely moved or removed the /stock endpoint, because orders-api (v2.3.0) now fails at startup with 'GET http://inventory.orders:8080/stock: HTTP Error 404' and exits 1. orders-api itself has not changed since it was created (revision 1). The link between API_VERSION and the 404 is inferred from the timing; I could not see the variable's value.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 is 0/1 ready with 3 restarts, terminated Error exit code 1; inventory-b775d96fd-qq86l is 1/1, age 44s
- `kubernetes_pod_logs`: orders-api logs: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago with env_added API_VERSION; orders-api has had no change since it was created 2m ago

**Recommendations**
1. Roll back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders), or remove or correct API_VERSION, so that /stock is served again.
2. Once inventory serves /stock, confirm orders-api becomes Ready, restarting it if the backoff delays recovery.
3. Agree on the inventory API version with the orders-api owners before rolling it out again.

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "tail_lines": 50}
5. `incidents_search` {"keywords": "orders-api"}
