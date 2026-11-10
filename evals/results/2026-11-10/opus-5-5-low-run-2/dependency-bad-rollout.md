## orders-api is crash looping (3 restarts, exit code 1) because it can't fetch stock at startup: GET http://inventory.orders:8080/stock returns 404. inventory was rolled out to revision 2, which added the env var API_VERSION, about 48s before this check, so that rollout is the likely cause.

**Root cause** (medium confidence, `bad_rollout`): inventory revision 2 (rolled out about 48s ago) added the env var API_VERSION. The most likely effect is that inventory now serves its API under a different, versioned path, so /stock returns 404. orders-api 2.3.0 treats a failed stock sync at startup as fatal and exits with code 1, which causes the crash loop. Two gaps: the API_VERSION value can't be seen, and the previous run's logs are gone, so I can't confirm that orders-api was healthy before inventory revision 2 went out.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 is 0/1 ready with 3 restarts, terminated with Error, exit code 1. The inventory pod is Running 1/1 and is 44s old.
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago and added the env var API_VERSION to container app. orders-api has not changed since it was created (revision 1).

**Recommendations**
1. Roll back the inventory deployment to revision 1 (kubectl rollout undo deployment/inventory -n orders), or remove or correct API_VERSION so /stock is served again.
2. Check that GET http://inventory.orders:8080/stock returns 200, and that orders-api becomes Ready.
3. If the API version change is intended, update the inventory URL in orders-api to the new path before rolling inventory forward again.
4. Consider making orders-api retry the stock sync instead of exiting when it fails at startup.

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 50}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api crash"}
