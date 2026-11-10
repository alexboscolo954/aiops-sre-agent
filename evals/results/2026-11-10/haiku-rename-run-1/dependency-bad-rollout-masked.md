## orders-api is crash looping (exit 1) because its startup stock sync calls GET /stock on the inventory service and gets HTTP 404. The inventory deployment rolled out revision 2 about 48s before the alert, adding API_VERSION, and its logs now say it serves /v2/stock, so the path orders-api expects no longer exists.

**Root cause** (high confidence, `bad_rollout`): inventory revision 2 (ReplicaSet inventory-b775d96fd, created 44s before triage, diff: env_added API_VERSION) changed the inventory service to serve /v2/stock. Its log reads 'inventory serving /v2/stock'. orders-api 2.3.0 (single revision, pod orders-api-568b7b8d9f-vzp22, restarts 3, last exit code 1) fails at startup with 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found' because it still calls /stock. The app exits on the first failure and has no retry, so the restarts keep going. Revision 1 of inventory had no env var, which points to the rollout as the trigger.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Pod/orders-api-568b7b8d9f-vzp22, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22 (container app, latest instance; previous logs gone): 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l (container app, current): 'inventory serving /v2/stock'
- `kubernetes_recent_changes`: orders/inventory revision 2 rollout 48s ago, diff env_added app: [API_VERSION]; revision 1 created 2m ago; orders-api revision 1 created 2m ago, no later rollout
- `kubernetes_describe_deployment`: inventory rollout_history: revision 2 (inventory-b775d96fd, 1 replica, env API_VERSION) is the current, Available revision; revision 1 (inventory-8469585669) scaled to 0 replicas
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22: ready 0/1, restarts 3, last_terminated Error exit_code 1
- `kubernetes_describe_pod`: orders-api container app: image python:3.12-alpine, memory limit 32Mi, env INVENTORY_URL, no probes; state terminated Error exit 1; BackOff event on the pod. Memory limit and OOM are not involved.

**Recommendations**
1. Roll back orders/inventory to revision 1 (kubectl rollout undo, or set API_VERSION back to its old state). This restores /stock, and orders-api should then start. Get approval before changing anything.
2. Alternatively, if v2 is intended, change orders-api's INVENTORY_URL or code to call /v2/stock, then redeploy orders-api. Confirm the change with the owners of both services first.
3. After the fix, confirm orders-api-568b7b8d9f-vzp22 (or its replacement) is 1/1 Ready and restarts stop. Check that the inventory /stock path returns 200.
4. Ask the inventory team to keep /stock working during the v2 transition, or to put the new route behind API_VERSION, so future rollouts do not break orders-api startup.
5. Consider adding a retry or a non-fatal startup for the stock sync in orders-api, so a dependency returning 404 does not crash-loop the pod.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders", "label_selector": ""}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "container": "app", "previous": true, "tail_lines": 50}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
7. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "container": "app", "previous": false, "tail_lines": 50}
8. `incidents_search` {"keywords": "orders-api inventory stock 404 crashloop", "days": 90, "limit": 5}
