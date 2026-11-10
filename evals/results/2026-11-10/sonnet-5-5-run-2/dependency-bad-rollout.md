## orders-api is crash looping (exit 1) because its startup call to inventory at /stock returns 404. The inventory deployment rolled out revision 2 just before, and it now serves /v2/stock.

**Root cause** (medium confidence, `bad_rollout`): Inventory revision 2 (rolled out about 44s ago) added the env var API_VERSION. Its log now reads "inventory serving /v2/stock", so the old /stock path returns 404. orders-api (version 2.3.0, unchanged revision 1) calls http://inventory.orders:8080/stock at startup and exits 1 with "FATAL: stock sync failed ... HTTP Error 404". orders-api's image pull finished about 48s ago, so every container start came after the inventory rollout. The 404 therefore fits the new revision. I did not see orders-api succeed against revision 1, so that link is inferred.
**Severity:** medium  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22 (latest instance; previous logs gone): "orders-api starting, version 2.3.0 / FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found"
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago, adding env var API_VERSION. orders-api has only its original revision 1, created 2m ago.
- `kubernetes_pod_logs`: The new inventory pod inventory-b775d96fd-qq86l logs "inventory serving /v2/stock", so the endpoint path changed.
- `kubernetes_describe_pod`: orders-api pod: 3 restarts, last exit code 1 (Error), BackOff warning. No OOM, probe or image problem. The pull completed 48s ago, after a FailedScheduling taint delay.
- `kubernetes_describe_deployment`: inventory rollout history: revision 1 had no env vars, revision 2 has API_VERSION. The image is the same (python:3.12-alpine), so the behaviour change comes from the env var.
- `runbooks_runbook_for_alert`: The pod-crashlooping runbook says exit code Error means the process failed, and a rollout of a dependency is the likely cause. The fix is a rollback or a config fix, not a restart.

**Recommendations**
1. Roll back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders), or remove or adjust API_VERSION, so /stock is served again. Then confirm orders-api recovers.
2. Alternatively, point orders-api at the new path by changing INVENTORY_URL or the app's stock path to /v2/stock. Do this only if the v2 API is intended.
3. Agree with the inventory owners on API versioning. Keep /stock available until consumers migrate.
4. Make orders-api retry the stock sync with backoff instead of exiting at startup.
5. Do not restart the orders-api pod. A restart does not fix this.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 30}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
7. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 20}
8. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
