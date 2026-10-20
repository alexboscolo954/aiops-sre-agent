## orders-api is crash looping because its startup stock sync calls http://inventory.orders:8080/stock and gets 404. The inventory deployment rolled out revision 2 about 44s before the alert, and it now serves /v2/stock, so the path orders-api expects no longer exists.

**Root cause** (medium confidence, `bad_rollout`): Inventory revision 2 (replicaset inventory-b775d96fd, created 44s before triage) added the API_VERSION env var to the inventory app. Its log now reads 'inventory serving /v2/stock'. orders-api 2.3.0 (revision 1, pod vzp22) exits on startup with 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'. orders-api has restarted 3 times with exit code 1 and is at 0/1 ready. The rollout changed the inventory API path that orders-api depends on, with no matching change on the orders-api side. The link between API_VERSION and the /v2 path is inferred from timing and the diff, not shown directly in the code.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Pod/orders-api-568b7b8d9f-vzp22, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22 (container app, current instance, previous logs gone): 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_describe_pod`: orders-api-568b7b8d9f-vzp22 app container: state terminated Error, exit_code 1, restarts 3, Ready False (ContainersNotReady), no liveness or readiness probes, env var INVENTORY_URL set
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l (container app): 'inventory serving /v2/stock'
- `kubernetes_describe_deployment`: inventory rollout_history: revision 2 (replicaset inventory-b775d96fd) created 44s ago with env added [API_VERSION]; revision 1 (inventory-8469585669) created 2m ago and now scaled to 0 replicas; deployment Available and Progressing
- `kubernetes_recent_changes`: inventory revision 2 rollout 48s ago, diff env_added app: [API_VERSION]; orders-api revision 1 created 2m ago with no later change
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22: Running, ready 0/1, restarts 3, last terminated Error exit 1; inventory-b775d96fd-qq86l 1/1 Running with 0 restarts
- `incidents_search`: No past Report in the last 90 days matches orders-api, inventory, or stock 404

**Recommendations**
1. Roll back inventory to revision 1 (replicaset inventory-8469585669), or otherwise restore the /stock path, so orders-api's startup stock sync gets 200. This needs human approval.
2. Alternatively, if /v2 is the intended API, point orders-api's stock sync at /v2/stock (or make the path configurable) and redeploy orders-api. Confirm which side owns the API contract first.
3. After the fix, confirm orders-api-568b7b8d9f-vzp22 (or its replacement) reaches 1/1 Ready and restarts stop increasing.
4. Add a startup contract check or a compatibility test between inventory and orders-api before rolling out API changes to inventory.

Runbook: `pod-crashlooping`

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders", "label_selector": ""}
2. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "container": "app", "previous": true, "tail_lines": 50}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
7. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "container": "app", "tail_lines": 50}
8. `incidents_search` {"keywords": "orders-api inventory stock 404", "days": 90, "limit": 5}
