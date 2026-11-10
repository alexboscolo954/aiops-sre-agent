## orders-api-568b7b8d9f-vzp22 is crash looping (exit 1, 3 restarts). At startup it calls GET http://inventory.orders:8080/stock and gets HTTP 404. This started after the inventory deployment rolled out revision 2 about 48s ago, which added the API_VERSION env var, and inventory now says it serves /v2/stock.

**Root cause** (medium confidence, `bad_rollout`): inventory revision 2 (ReplicaSet inventory-b775d96fd, created about 44-48s ago) added the API_VERSION env var. The new inventory pod logs 'inventory serving /v2/stock', so the stock endpoint appears to have moved to /v2. orders-api 2.3.0 still calls the old path and treats the failed stock sync as fatal: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found', then exits with code 1. Revision 1 had no API_VERSION. Two things I could not confirm: that inventory.orders is the inventory service, and whether orders-api also crashed before revision 2 (the pod is 2m old with 3 restarts, and inventory revision 1 was also failing readiness while it started). The 404 on /stock alongside the /v2/stock log line is the deciding evidence.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 shows Ready 0/1, restarts 3, terminated Error exit_code 1. inventory-b775d96fd-qq86l is Running 1/1, 44s old.
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22: 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'. inventory-b775d96fd-qq86l: 'inventory serving /v2/stock'.
- `kubernetes_recent_changes`: inventory rolled out revision 2 48s ago with env_added API_VERSION. orders-api has had no changes since it was created (revision 1) 2m ago.
- `kubernetes_describe_deployment`: inventory revision 2 (inventory-b775d96fd) sets env API_VERSION. Revision 1 (inventory-8469585669) had no env vars. The image python:3.12-alpine is the same in both.
- `kubernetes_get_events`: Repeated BackOff restarting the failed app container in orders-api-568b7b8d9f-vzp22 (count 3, last 3s ago).

**Recommendations**
1. Roll back inventory to revision 1 (kubectl -n orders rollout undo deployment/inventory --to-revision=1) so /stock is served again. Then confirm orders-api becomes Ready.
2. Check that inventory.orders is the inventory Service, and look at what value API_VERSION is set to in inventory revision 2.
3. Before re-applying the API_VERSION change, either keep serving the old /stock path in inventory, or update orders-api to call /v2/stock and roll it out first.
4. Optionally, make orders-api retry or fail softer on stock sync errors instead of exiting at startup. Don't restart the pod: a restart won't fix the crash loop.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api crashloop"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 50}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
7. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 50}
8. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders"}
