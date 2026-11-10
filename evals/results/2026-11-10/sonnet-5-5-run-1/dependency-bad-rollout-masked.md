## orders-api is crash looping because its startup stock sync gets HTTP 404 from the inventory service. Inventory revision 2 rolled out just before and now serves /v2/stock, not /stock.

**Root cause** (medium confidence, `bad_rollout`): Inventory rollout revision 2, about 48s ago, added the env var API_VERSION. Inventory now logs "inventory serving /v2/stock". orders-api (INVENTORY_URL set) calls GET /stock at startup. It gets a 404, logs "FATAL: stock sync failed" and exits with code 1. orders-api has no retry or fallback. Its image pull finished at about 48s, so its first start came after the inventory rollout. The link between the two changes is inferred from timing and logs. I did not see the inventory code or the orders-api config for the path.
**Severity:** medium  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api pod logs: "orders-api starting, version 2.3.0" then "FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found". The previous instance's logs were gone, so this is the latest instance.
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago, adding env var API_VERSION. orders-api has only its revision 1 from 2m ago, with no change.
- `kubernetes_describe_deployment`: inventory revision 2 (ReplicaSet inventory-b775d96fd) has env API_VERSION. Revision 1 had no env vars.
- `kubernetes_describe_pod`: The orders-api pod restarted 3 times and shows BackOff events. Its exit code is 1 (Error), not OOM. It has env INVENTORY_URL, and no probes. The image pull finished about 48s ago.
- `kubernetes_pod_logs`: The new inventory pod inventory-b775d96fd-qq86l logs "inventory serving /v2/stock", so the old /stock path is no longer served.

**Recommendations**
1. Roll back inventory to revision 1 (or remove API_VERSION) to restore /stock. This should let orders-api recover on its next restart.
2. Alternatively, update orders-api to call /v2/stock (for example through INVENTORY_URL or its config) if the versioned API is intended. Coordinate the two changes.
3. Make orders-api retry the stock sync with backoff, or tolerate a failed sync, instead of exiting at startup.
4. Add a readiness probe and a compatibility check to inventory rollouts so that breaking path changes are caught before dependents break.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
7. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l"}
8. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
