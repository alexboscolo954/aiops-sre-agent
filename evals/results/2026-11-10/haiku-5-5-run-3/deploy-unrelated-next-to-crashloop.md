## The audit change is healthy. orders-api, which was already failing, is in CrashLoopBackOff with a 404 from inventory /stock. Its failure predates the change, and I could not confirm that the change made it fail in a new way, so the Check fails.

**Root cause** (low confidence, `dependency_failure`): orders-api (python:3.12-alpine, revision 2, created 1h ago) exits with 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404'. The inventory pod logs 'inventory serving /v2/stock', so the path it serves differs from the /stock path orders-api requests. This points to an API path or version mismatch (the inventory change added API_VERSION). The inventory change is the only related rollout, but the active inventory ReplicaSet is revision 6 (23h old), so the 14m-old revision 5 is not what is serving now. Confidence is low because I could not read the pre-change logs.
**Severity:** high  ·  **Affected:** orders/deployment/orders-api

**Evidence**
- `kubernetes_pod_logs`: orders-api-79cd5d49dc-28wnk previous logs: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'.
- `kubernetes_pod_logs`: inventory-b775d96fd-rmlvd logs: 'inventory serving /v2/stock'.
- `kubernetes_list_pods`: orders-api-79cd5d49dc-28wnk 0/1, restarts 17, CrashLoopBackOff, last terminated Error exit 1.
- `kubernetes_describe_deployment`: inventory revision 5 created 14m ago (env API_VERSION, BUILD); revision 6 (inventory-b775d96fd) created 23h ago is the current ReplicaSet.

**Recommendations**
1. Confirm the inventory API path that orders-api expects (/stock versus /v2/stock) and the API_VERSION setting, then fix the mismatch in config or code.
2. Check the orders-api INVENTORY_URL env value.
3. If the mismatch is caused by a recent change, roll back the change for the affected workload. Do not restart the pod alone, since that will not fix a crash loop.

Runbook: `pod-crashlooping`

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 30}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders", "warnings_only": true}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "audit"} (error)
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "audit-6cfdd68f8c-2xr5p", "container": "pause"} (error)
6. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "audit-6cfdd68f8c-2xr5p"}
7. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
8. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-79cd5d49dc-28wnk", "tail_lines": 50} (error)
9. `incidents_search` {"keywords": "orders-api CrashLoopBackOff"}
10. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-79cd5d49dc-28wnk", "previous": true}
11. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-79cd5d49dc-28wnk"}
12. `runbooks_runbook_for_alert` {"alertname": "orders-api CrashLoopBackOff"}
13. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-rmlvd"} (error)
14. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-rmlvd", "tail_lines": 30}
15. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "orders-api"}
16. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
17. `runbooks_read_runbook` {"name": "pod-crashlooping"}
18. `CheckResult` {"passed": false, "summary": "The changed deployment 'audit' (revision 1, created 2m ago) is healthy: 1/1 ready, 0 restarts, no warning events, and nothing failing in its logs. However, 'inventory' rollout 5 (14m ago, added env API_VERSION and BUILD) is a changed deployment and is running healthy (1
19. `CheckResult` {"passed": false, "summary": "The changed deployment 'audit' (revision 1, created 2m ago) is healthy: 1/1 ready, 0 restarts, no warning events. The 'inventory' rollout (revision 5, 14m ago, env API_VERSION and BUILD added) is also healthy: 1/1 ready, 0 restarts, logs show 'inventory serving /v2/stoc
