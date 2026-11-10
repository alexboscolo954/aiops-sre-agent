## orders-api (namespace orders) is down at 0/1 ready and crash-looping because its startup stock sync calls inventory's /stock endpoint, which now returns 404 after inventory's revision 2 rollout. inventory itself is healthy (1/1).

**Root cause** (medium confidence, `bad_rollout`): inventory revision 2 (rolled out about 48s before the check, adding env API_VERSION) now serves /v2/stock. orders-api 2.3.0 still calls http://inventory.orders:8080/stock, gets HTTP 404, and exits with code 1 on startup. orders-api revision 1 is unchanged, so the inventory rollout is the trigger. Confidence is medium: the logs show the 404 and the timing matches, but the link between API_VERSION and the path change is inferred.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_list_deployments`: orders-api ready 0/1, Available=False reason MinimumReplicasUnavailable; inventory ready 1/1.
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 Running but 0/1 ready, restarts 3, container app terminated Error exit code 1.
- `kubernetes_pod_logs`: orders-api log: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'.
- `kubernetes_pod_logs`: inventory log: 'inventory serving /v2/stock'.
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago with env_added API_VERSION; orders-api revision 1 unchanged since created 2m ago.

**Recommendations**
1. Confirm with the inventory owners whether /stock moved to /v2/stock in revision 2 and whether the old path is intentionally gone.
2. Point orders-api at the /v2/stock path (or match its inventory API version), or roll inventory back to revision 1 if the path change was unintended.
3. Rolling inventory back to revision 1 is the fastest low-risk restore; it needs human approval and was not run.
4. After the fix, confirm orders-api reaches 1/1 ready and the orders namespace passes the check.

Runbook: `deployment-unavailable`

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
6. `incidents_search` {"keywords": "orders-api inventory stock sync 404"}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
8. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l"}
9. `runbooks_search_runbooks` {"keywords": "orders deployment not ready replicas"}
10. `runbooks_read_runbook` {"name": "deployment-unavailable"}
11. `CheckResult` {"passed": false, "summary": "The Check does not hold. Deployment orders-api in namespace orders has 0/1 replicas ready and is crash-looping. Deployment inventory is healthy (1/1).", "evidence": [{"source": "kubernetes_list_deployments", "finding": "orders-api ready 0/1, condition Available=False re
12. `CheckResult` {"passed": false, "summary": "The Check does not hold. Deployment orders-api in namespace orders has 0/1 replicas ready and is crash-looping on a failed stock sync against inventory. Deployment inventory is healthy (1/1).", "evidence": [{"source": "kubernetes_list_deployments", "finding": "orders-ap
13. `CheckResult` {"passed": false, "summary": "The Check does not hold. Deployment orders-api in namespace orders has 0/1 replicas ready and is crash-looping on a failed stock sync against inventory. Deployment inventory is healthy (1/1).", "evidence": [{"source": "kubernetes_list_deployments", "finding": "orders-ap
14. `CheckResult` {"passed": false, "summary": "The Check does not hold. Deployment orders-api in namespace orders has 0/1 replicas ready and is crash-looping on a failed stock sync against inventory. Deployment inventory is healthy (1/1).", "evidence": [{"source": "kubernetes_list_deployments", "finding": "orders-ap
15. `CheckResult` {"passed": false, "summary": "The Check does not hold. Deployment orders-api in namespace orders has 0/1 replicas ready and is crash-looping on a failed stock sync against inventory. Deployment inventory is healthy (1/1).", "evidence": [{"source": "kubernetes_list_deployments", "finding": "orders-ap
