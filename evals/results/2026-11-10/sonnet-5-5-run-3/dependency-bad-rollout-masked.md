## orders-api is crash looping because its startup stock sync gets HTTP 404 from the inventory service. Inventory revision 2 rolled out about 48s ago and now serves /v2/stock instead of /stock.

**Root cause** (medium confidence, `bad_rollout`): Inventory revision 2 added the env var API_VERSION. Its log now reads "inventory serving /v2/stock", so the stock endpoint moved to /v2/stock. orders-api (version 2.3.0, revision 1, unchanged) still calls GET http://inventory.orders:8080/stock at startup. It gets a 404, logs "FATAL: stock sync failed" and exits with code 1. The orders-api image pull finished about 48s ago, which is when inventory revision 2 appeared. The first orders-api start therefore came after the inventory rollout. The inventory log, the 404 and the matching timing make this likely, but the exact inventory path change is inferred from its log line.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22 logs: "orders-api starting, version 2.3.0" then "FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found". These are the latest instance's logs, because the previous instance's logs were gone.
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago, adding env var API_VERSION. orders-api only has revision 1, created 2m ago and unchanged.
- `kubernetes_describe_deployment`: inventory revision 2 (ReplicaSet inventory-b775d96fd) has env API_VERSION. Revision 1 had no env vars. The image is the same, python:3.12-alpine.
- `kubernetes_describe_pod`: orders-api container terminated with Error, exit code 1, restarts 3, and BackOff events. There are no OOM kills and no probes. The image pull finished about 48s ago, after the earlier FailedScheduling event.
- `kubernetes_list_pods`: orders-api pod is 0/1 ready with exit code 1. The inventory pod inventory-b775d96fd-qq86l is running and ready, 44s old, with 0 restarts.

**Recommendations**
1. Roll back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders). Revision 1 served /stock, so orders-api should then start. This needs human approval.
2. Or update orders-api to call the /v2/stock endpoint (change INVENTORY_URL or the client code). Confirm with the inventory owners that /v2/stock is the intended API.
3. Avoid breaking API changes in inventory. Keep /stock available alongside /v2/stock until its consumers have migrated, and gate the rollout on consumer compatibility.
4. Do not restart orders-api as a fix. The crash is deterministic until the endpoint mismatch is resolved.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api crash looping"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 30}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
7. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l"}
8. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
