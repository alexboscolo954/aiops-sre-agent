## orders-api is crash looping because its startup stock sync gets HTTP 404 from inventory.orders /stock. The inventory deployment's revision 2, rolled out about 44s before the alert, added API_VERSION and now serves /v2/stock, so the path orders-api calls no longer exists.

**Root cause** (medium confidence, `bad_rollout`): orders-api 2.3.0 exits with code 1 at startup: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'. The inventory deployment rolled out revision 2 (ReplicaSet inventory-b775d96fd, created 44s before the alert), which added env API_VERSION to the app container. The inventory pod logs now say 'inventory serving /v2/stock', so inventory moved its API to /v2/stock while orders-api still calls /stock. Revision 1 (inventory-8469585669, now scaled to 0) had no env vars. orders-api has only revision 1, which has never started successfully, so there is no earlier working orders-api revision to roll back to. The fix belongs on the inventory side.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22 (previous instance, shown as latest): 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_describe_pod`: Container app exit_code 1, last_state Error, restarts 3, no liveness or readiness probe; env contains INVENTORY_URL; Ready False (ContainersNotReady)
- `kubernetes_recent_changes`: inventory revision 2 rollout 48s ago with diff env_added app: [API_VERSION]; orders-api only has revision 1 created 2m ago
- `kubernetes_describe_deployment`: inventory: rollout_history revision 2 (inventory-b775d96fd, 44s) with env [API_VERSION], revision 1 (inventory-8469585669) with no env, now 0 replicas; orders-api: Available False, MinimumReplicasUnavailable
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l app container log: 'inventory serving /v2/stock'
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 ready 0/1, restarts 3, last terminated Error exit 1; inventory-b775d96fd-qq86l Running 1/1 with 0 restarts
- `incidents_search`: No past Report in the last 90 days matches orders-api crashloop

**Recommendations**
1. Confirm with the inventory owners that the /v2/stock change from API_VERSION in revision 2 is intended. Check whether orders-api 2.3.0 expects /stock or /v2/stock.
2. If the change is not intended, roll back the inventory deployment to revision 1 (or remove the API_VERSION env var). This needs human approval. Then confirm the orders-api pod stops crashing and goes Ready.
3. Alternatively, if /v2/stock is intended, point orders-api at the new path (for example by setting INVENTORY_URL or fixing the code) and roll out a new orders-api revision. This is a config or code change, not a restart.
4. Do not restart orders-api alone. The crash is deterministic at startup, so restarting it will not fix the loop.
5. After the fix, check the orders-api rollout and confirm the crash loop alert clears.

Runbook: `pod-crashlooping`

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders", "label_selector": ""}
2. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "container": "app", "previous": true, "tail_lines": 50}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
6. `incidents_search` {"keywords": "orders-api crashloop", "days": 90, "limit": 5}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
8. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "container": "app", "tail_lines": 50}
9. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "orders-api"}
