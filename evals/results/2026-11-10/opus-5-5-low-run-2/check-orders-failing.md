## orders-api has 0/1 replicas ready. Its pod orders-api-568b7b8d9f-vzp22 keeps exiting with code 1 at startup (3 restarts) because GET http://inventory.orders:8080/stock returns 404. This began right after the inventory rollout to revision 2.

**Root cause** (medium confidence, `bad_rollout`): Inventory was rolled out to revision 2 48s ago, and the only change was a new env var, API_VERSION. orders-api 2.3.0 checks stock against inventory when it starts, and that call now gets HTTP 404 from inventory's /stock endpoint, so orders-api exits fatally. Most likely API_VERSION changed inventory's API paths and /stock no longer exists. I haven't confirmed this: I didn't read inventory's logs or its config.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_list_deployments`: orders-api 0/1 ready (MinimumReplicasUnavailable)
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 is 0/1 ready with 3 restarts, last exit code 1 (Error)
- `kubernetes_pod_logs`: orders-api log: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_recent_changes`: inventory went to revision 2 48s ago, adding env var API_VERSION; orders-api has not changed since it was created

**Recommendations**
1. Roll inventory back to revision 1 (kubectl rollout undo deployment/inventory -n orders), or remove API_VERSION from it.
2. Check that orders-api becomes ready once /stock answers again.
3. Agree on the inventory API version with the orders-api team before rolling revision 2 out again.

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders", "label_selector": "app=orders-api"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 50}
