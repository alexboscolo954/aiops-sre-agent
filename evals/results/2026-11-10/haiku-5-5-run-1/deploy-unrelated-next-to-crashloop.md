## The changed deployment 'audit' (revision 1, created 2m ago) is healthy: 1/1 ready, 0 restarts, no warning events. The Check fails because orders-api, already failing before the change, is still in CrashLoopBackOff (17 restarts, 0/1 ready) with a 404 on inventory's /stock endpoint. The inventory rollout 14m ago is the nearest lead.

**Root cause** (medium confidence, `dependency_failure`): orders-api (python:3.12-alpine, INVENTORY_URL env, revision 2 unchanged for 1h) fails at startup with 'stock sync failed: GET http://inventory.orders:8080/stock: HTTP 404'. The inventory service serves '/v2/stock' per its own log ('inventory serving /v2/stock'), so the path orders-api calls no longer exists. Inventory moved to revision 5 (14m ago, env added API_VERSION and BUILD) and revision 6 is now current. The 404 is therefore most likely an API path mismatch between orders-api and inventory. The Check was told orders-api was already failing before the change, so it is not this change's doing; the audit change itself did not cause it. Confidence is medium, because the inventory revision-5 diff does not show a path change and the link is inferred.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_recent_changes`: audit deployment revision 1 'created' 2m ago, empty diff; inventory revision 5 'rollout' 14m ago with env_added API_VERSION, BUILD.
- `kubernetes_list_pods`: audit-6cfdd68f8c-2xr5p Running 1/1, restarts 0, age 2m; orders-api-79cd5d49dc-28wnk 0/1, restarts 17, CrashLoopBackOff, last exit code 1.
- `kubernetes_get_events`: Warning BackOff on orders-api pod (count 55, last seen 4m); Warning Unhealthy readiness probe failures on inventory pods 11m and 14m ago (connection refused); no warning events for audit.
- `kubernetes_list_deployments`: audit ready 1/1 updated 1 with no problems; orders-api ready 0/1, Available=False MinimumReplicasUnavailable.
- `kubernetes_pod_logs`: orders-api previous run: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'.
- `kubernetes_pod_logs`: inventory-b775d96fd-rmlvd log: 'inventory serving /v2/stock' (service serves /v2/stock, while orders-api requests /stock).
- `kubernetes_describe_deployment`: orders-api revision 2 (1h old) unchanged config (INVENTORY_URL); inventory revision 6 current, 1/1 available.

**Recommendations**
1. Confirm the path orders-api calls for inventory stock (/stock) against the path inventory serves (/v2/stock), and fix whichever side is wrong (orders-api config or inventory route).
2. Check inventory revision 5 vs 6 (API_VERSION, BUILD env) to see whether the API version change moved the stock endpoint.
3. Owners of orders-api should fix the startup dependency; no automated restart will help while the 404 persists.

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 30}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders"}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "audit"} (error)
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "audit-6cfdd68f8c-2xr5p"} (error)
6. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
7. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "audit-6cfdd68f8c-2xr5p"}
8. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "orders-api"}
9. `incidents_search` {"keywords": "orders-api"}
10. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-79cd5d49dc-28wnk", "previous": true}
11. `runbooks_search_runbooks` {"keywords": "orders-api inventory stock sync"}
12. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-rmlvd"}
13. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
14. `incidents_read` {"id": "none"} (error)
15. `CheckResult` {"passed": false, "summary": "The changed deployment 'audit' (revision 1, created 2m ago) is healthy: 1/1 ready, 0 restarts, no warning events. But the Check fails on the rule that nothing else in the namespace may start failing: orders-api (already failing before the change) is still in CrashLoopBa
16. `CheckResult` {"passed": false, "summary": "The changed deployment 'audit' (revision 1, created 2m ago) is healthy: 1/1 ready, 0 restarts, no warning events. The Check fails because orders-api, already failing before the change, is still in CrashLoopBackOff (17 restarts, 0/1 ready). Its previous log shows a stock
