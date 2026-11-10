## orders-api is crash looping because its startup call to the inventory service, GET /stock, returns 404. inventory revision 2 rolled out about 48s ago and now serves /v2/stock.

**Root cause** (medium confidence, `bad_rollout`): inventory revision 2 added the env var API_VERSION, and the service now serves /v2/stock (inventory log: "inventory serving /v2/stock"). orders-api still calls the old /stock path via INVENTORY_URL. It gets HTTP 404 and exits 1 on the "stock sync failed" fatal error, with no retry. orders-api has only one revision, so the breakage comes from the dependency's rollout. The orders-api container image was pulled about 48s ago, which fits it first starting around the time of the inventory rollout. The exact timing against the first crash is not fully pinned down. I did not see the inventory code or the revision 1 behaviour, so the claim that /stock used to work is inferred.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api pod logs: "orders-api starting, version 2.3.0" then "FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found". The previous instance's logs were gone, so these are the latest instance's logs.
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago and added env var API_VERSION. orders-api and inventory revision 1 were created 2m ago.
- `kubernetes_describe_deployment`: inventory has revisions 1 (no env) and 2 (env API_VERSION). orders-api has only revision 1, with INVENTORY_URL as its only env var, so its own config did not change.
- `kubernetes_pod_logs`: The inventory pod's log shows it now serves "/v2/stock", not /stock.
- `kubernetes_describe_pod`: orders-api pod: 3 restarts, last state Error exit code 1, BackOff warning events, and no probes configured. The image was pulled 48s ago, after the node was initially unschedulable (a taint).

**Recommendations**
1. Roll back inventory to revision 1 (kubectl rollout undo deploy/inventory -n orders) to restore the /stock path quickly, or keep inventory revision 2 and fix orders-api (next step).
2. Alternatively, update orders-api to call /v2/stock, for example by setting INVENTORY_URL or the code path to the v2 endpoint, then roll it out.
3. Ask the inventory owners whether the API_VERSION / v2 path change was intentional, and whether /stock should stay as a backward-compatible alias.
4. Add retry and backoff for the startup stock sync in orders-api. Add a readiness probe so a failing dependency does not cause a hard crash loop.
5. Do not restart the orders-api pod. The crash will recur until the path mismatch is fixed.

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
9. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "orders-api"}
