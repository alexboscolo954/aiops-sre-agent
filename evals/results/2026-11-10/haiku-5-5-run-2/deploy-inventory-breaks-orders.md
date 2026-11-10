## orders-api is crash-looping (0/1 ready, 3 restarts, exit 1) right after the inventory revision 2 rollout. Its log shows the stock sync against inventory.orders:8080/stock returns 404, while the inventory pod reports it serves /v2/stock. The inventory change itself is healthy (1/1 ready, 0 restarts), so the fault is the mismatch between orders-api's call and inventory's endpoint.

**Root cause** (medium confidence, `dependency_failure`): orders-api calls GET http://inventory.orders:8080/stock on startup and exits 1 on the 404. The inventory pod logs 'inventory serving /v2/stock', so the path served differs from the path orders-api requests. The revision 2 change (env API_VERSION added to inventory) is the only change in the namespace and is the likely trigger, but the logs do not show how API_VERSION alters the served path. Confidence is medium.
**Severity:** high  ·  **Affected:** orders/deployment/orders-api, orders/deployment/inventory

**Evidence**
- `kubernetes_recent_changes`: inventory revision 2 rollout 48s ago, diff env_added app: [API_VERSION]. inventory revision 1 and orders-api revision 1 were both created 2m ago. No other rollouts.
- `kubernetes_list_pods`: inventory-b775d96fd-qq86l Running 1/1, restarts 0, age 44s. orders-api-568b7b8d9f-vzp22 Running 0/1, restarts 3, last terminated Error exit code 1.
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l: 'inventory serving /v2/stock'.
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22 (previous=true, latest instance shown): 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'.
- `kubernetes_describe_deployment`: orders-api: replicas 0/1 ready, Available=False MinimumReplicasUnavailable, only revision 1 (env INVENTORY_URL).
- `kubernetes_get_events`: Warning BackOff on orders-api-568b7b8d9f-vzp22 (count 3). Warning Unhealthy: inventory-b775d96fd-qq86l readiness probe failed 'connection refused' (count 1, 44s ago).

**Recommendations**
1. Compare the path inventory serves at revision 2 (/v2/stock) with the path orders-api requests (/stock). Check the inventory API_VERSION setting and the orders-api INVENTORY_URL value.
2. If the API_VERSION change moved the endpoint, roll inventory back to revision 1 (kubectl rollout undo deployment/inventory -n orders), or correct API_VERSION, then confirm orders-api reaches Ready.
3. Do not restart orders-api on its own: the 404 is deterministic, so a restart will not fix it.
4. After the fix, re-run this Check: inventory 1/1 with no restarts, orders-api 1/1 with no new restarts, and no new warning events.

Runbook: `pod-crashlooping`

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 30}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders", "warnings_only": true}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l"}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true}
7. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
8. `incidents_search` {"keywords": "inventory orders-api"}
9. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
10. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "orders-api"}
11. `runbooks_search_runbooks` {"keywords": "orders-api inventory crashloop 404 dependency"}
12. `runbooks_read_runbook` {"name": "pod-crashlooping"}
13. `CheckResult` {"passed": false, "summary": "The inventory change (revision 2, which added env API_VERSION) is healthy: 1/1 ready, 0 restarts, and its logs are clean. But the check fails because the orders-api deployment in the same namespace is failing: its pod is CrashLoopBackOff (3 restarts, exit 1) with \"FATA
14. `CheckResult` {"passed": false, "summary": "The inventory change (revision 2, which added env API_VERSION) is healthy: 1/1 ready, 0 restarts, logs clean. The check fails because orders-api, in the same namespace, is in CrashLoopBackOff: 0/1 ready, 3 restarts, exit 1, with \"FATAL: stock sync failed: GET http://in
15. `CheckResult` {"passed": false, "summary": "The inventory change (revision 2, which added env API_VERSION) is healthy: 1/1 ready, 0 restarts, logs clean. The check fails because orders-api, in the same namespace, is in CrashLoopBackOff: 0/1 ready, 3 restarts, exit 1, with \"FATAL: stock sync failed: GET http://in
