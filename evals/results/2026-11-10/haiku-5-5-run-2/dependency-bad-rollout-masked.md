## orders-api pod orders-api-568b7b8d9f-vzp22 is crash looping (exit 1, 3 restarts) because its startup stock sync gets HTTP 404 from the inventory service's /stock endpoint. The inventory service was rolled to revision 2 (adding API_VERSION) about a minute before the alert, and it now serves /v2/stock, so the old /stock path no longer exists. This is a dependency contract mismatch, not a memory or scheduling problem.

**Root cause** (medium confidence, `bad_rollout`): The orders-api (v2.3.0, revision 1, INVENTORY_URL is its only config) fails at startup with "FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found" and exits 1. The inventory deployment rolled to revision 2 (env API_VERSION added) 48s before the alert, and its current log says "inventory serving /v2/stock". The inventory service moved its stock endpoint to /v2/stock, so orders-api's hardcoded /stock path now returns 404. orders-api has no retry, so it crash-loops. The orders-api deployment itself has not changed since its revision 1.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Pod/orders-api-568b7b8d9f-vzp22, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api latest instance (previous logs gone): 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 0/1 ready, restarts 3, last terminated Error exit code 1
- `kubernetes_recent_changes`: orders/inventory rolled to revision 2 at 48s ago, env_added API_VERSION on app; orders-api has only revision 1 (created 2m ago, no diff)
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l (revision 2) logs: 'inventory serving /v2/stock'
- `kubernetes_describe_pod`: orders-api container env names only INVENTORY_URL; no probes; limits 32Mi, so OOM is not the cause; exit code 1 with no OOMKilled
- `kubernetes_describe_deployment`: orders-api rollout history has only revision 1; Available=False MinimumReplicasUnavailable

**Recommendations**
1. Confirm the inventory contract change with the inventory owners: check whether /stock was intentionally moved to /v2/stock and whether /stock is kept as a compatibility alias.
2. Fastest safe fix: roll inventory back to revision 1 (which served /stock) so orders-api can start. This needs approval; do not do it without confirming the owners agree.
3. Alternative fix: point orders-api at the new path (e.g., INVENTORY_URL or the stock path to /v2/stock) and roll out a new orders-api revision. Check that orders-api 2.3.0 supports /v2/stock first.
4. Consider making the startup stock sync retry with backoff rather than exiting, so a dependency's brief unavailability does not crash-loop the service.
5. Confirm the fix: orders-api pod reaches 1/1 Ready and restarts stop.

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
6. `incidents_search` {"keywords": "orders-api crashloop"}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "orders-api"}
8. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l"}
9. `runbooks_read_runbook` {"name": "pod-crashlooping"}
10. `TriageReport` {"summary": "orders-api pod orders-api-568b7b8d9f-vzp22 is crash looping (exit 1, 3 restarts) because its startup stock sync gets HTTP 404 from the inventory service's /stock endpoint. The inventory service was rolled to revision 2 (adding API_VERSION) about a minute before the alert, and it now ser
