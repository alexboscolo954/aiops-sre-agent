## orders-api is crash looping (exit 1, 3 restarts). On startup it calls GET http://inventory.orders:8080/stock and gets a 404. The inventory deployment rolled out revision 2 about 48s ago, which added the env var API_VERSION, so that rollout most likely broke the endpoint.

**Root cause** (medium confidence, `bad_rollout`): Inventory revision 2 (rolled out about 48s ago) added the env var API_VERSION. This most likely moved or removed the /stock endpoint: orders-api 2.3.0 now logs 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found' and exits 1. Two gaps: inventory's own logs were not read, and the crashed run's logs were gone, so the logs shown come from the latest run. Also, orders-api's last exit (26s ago) came after the rollout, but its 2m age suggests it may have crashed before it too, so the timing is not a clean match.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22 (latest run; previous logs gone): 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 is 0/1 ready with 3 restarts, terminated Error exit code 1; the inventory pod is Running, 44s old
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago with env_added API_VERSION; orders-api has been unchanged since it was created

**Recommendations**
1. Check what API_VERSION is set to in inventory revision 2 and whether that version still serves /stock (inventory logs, or curl it from inside the cluster).
2. Roll back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders), or set API_VERSION to a version orders-api supports.
3. Check that orders-api recovers after the fix. Consider letting it retry the stock sync instead of exiting with a fatal error.

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 50}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api crashloop"}
