## The inventory revision 2 rollout (adds API_VERSION env) left inventory 1/1 Ready, but orders-api, which depends on it, is crash-looping with a 404 from inventory's /stock endpoint. The Check fails on the downstream breakage and the warning events.

**Root cause** (medium confidence, `dependency_failure`): inventory revision 2 changed the app's serving behaviour (inventory now logs 'serving /v2/stock', and orders-api gets HTTP 404 from GET http://inventory.orders:8080/stock). Inventory's env change (API_VERSION added) is the only change in the namespace, so it is the likely trigger, though the logs do not state the link explicitly. orders-api revision 1 is unchanged and was 0/1 Ready at check time.
**Severity:** high  ·  **Affected:** orders/deployment/inventory, orders/deployment/orders-api

**Evidence**
- `kubernetes_recent_changes`: inventory revision 2 rollout 48s ago: env_added app: API_VERSION. orders-api revision 1 unchanged, created 2m ago.
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 Running 0/1, 3 restarts, last terminated Error exit code 1. inventory-b775d96fd-qq86l Running 1/1, 0 restarts.
- `kubernetes_get_events`: Warning BackOff on orders-api pod (count 3). Warning Unhealthy readiness probe 'connection refused' on inventory-b775d96fd-qq86l (44s ago).
- `kubernetes_pod_logs`: orders-api: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'.
- `kubernetes_pod_logs`: inventory: 'inventory serving /v2/stock'.
- `kubernetes_describe_deployment`: orders-api: replicas 0/1 ready, Available False, MinimumReplicasUnavailable.

**Recommendations**
1. Confirm what inventory serves at /stock versus /v2/stock and whether the revision 2 change moved the endpoint; compare the inventory app code or config against revision 1.
2. Either roll inventory back to revision 1 (kubectl rollout undo) or fix the endpoint/INVENTORY_URL so orders-api can reach /stock; rollback is the low-risk option and needs approval.
3. After the fix, confirm orders-api reaches 1/1 Ready with no new restarts and no new warning events.
4. Check the inventory readiness probe 'connection refused' warning (44s ago) to confirm it has cleared.

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 30}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders", "warnings_only": true}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l"}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "orders-api"}
8. `incidents_search` {"keywords": "inventory orders-api"}
9. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
10. `CheckResult` {"passed": false, "summary": "The inventory rollout (revision 2, which added API_VERSION env) is not healthy. Its pod is Ready 1/1 with 0 restarts, but the change broke the dependent orders-api, which is 0/1 ready with 3 restarts and crashes with \"stock sync failed: GET http://inventory.orders:8080
11. `CheckResult` {"passed": false, "summary": "The inventory rollout (revision 2, which added API_VERSION env) is not healthy. Its pod is Ready 1/1 with 0 restarts, but the change broke the dependent orders-api, which is 0/1 ready with 3 restarts and crashes with \"stock sync failed: GET http://inventory.orders:8080
