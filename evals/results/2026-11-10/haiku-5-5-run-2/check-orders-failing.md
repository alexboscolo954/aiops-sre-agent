## orders-api (namespace orders) is down at 0/1 ready and crash-looping because its startup stock sync calls inventory's /stock path, which now returns 404. The inventory deployment was rolled out to revision 2 about 48 seconds before the check, and it now serves /v2/stock.

**Root cause** (medium confidence, `dependency_failure`): orders-api 2.3.0 fails at startup with 'stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404'. The inventory revision 2 rollout (~48s before the check, adding env API_VERSION) is running and its logs say 'inventory serving /v2/stock', so the API path appears to have moved from /stock to /v2/stock. orders-api itself was not changed (revision 1 only), so this looks like an inventory/orders API contract mismatch caused by the inventory rollout. This is inferred from logs and timing, not confirmed by inventory's config. No past incident matched.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_list_deployments`: orders-api ready 0/1, Available=False MinimumReplicasUnavailable; inventory 1/1.
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 0/1 ready, 3 restarts, exit code 1.
- `kubernetes_pod_logs`: orders-api: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'.
- `kubernetes_recent_changes`: inventory rollout to revision 2 at 48s, env added API_VERSION; no orders-api change since its creation 2m ago.
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l: 'inventory serving /v2/stock'.
- `kubernetes_describe_deployment`: inventory revision 2 Available; revision 1 had no env vars.

**Recommendations**
1. Confirm the inventory API change: check whether /stock was intentionally moved to /v2/stock and whether API_VERSION controls the path.
2. Choose a fix: either roll inventory back to revision 1 (kubectl rollout undo, which needs approval), or point orders-api at the /v2/stock path or a compatible API version, then redeploy orders-api.
3. After the fix, confirm orders-api reaches 1/1 ready and the deployment's Available condition is True.
4. Check other consumers of inventory /stock, since they may also return 404.

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
6. `incidents_search` {"keywords": "orders-api inventory stock sync 404"}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
8. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l"}
9. `runbooks_search_runbooks` {"keywords": "orders deployment not ready replicas crashloop"}
10. `runbooks_read_runbook` {"name": "deployment-unavailable"}
11. `CheckResult` {"passed": false, "summary": "The check fails: deployment orders-api in namespace orders has 0/1 replicas ready. Its only pod is crash-looping with exit code 1 (3 restarts). inventory is healthy (1/1).", "evidence": [{"source": "kubernetes_list_deployments", "finding": "orders-api ready 0/1, Availab
