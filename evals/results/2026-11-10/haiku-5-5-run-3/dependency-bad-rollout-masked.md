## orders-api pod vzp22 is crash looping (exit 1) because its startup stock sync calls inventory's /stock endpoint and gets HTTP 404. The inventory deployment was rolled out 44s before the alert (revision 2 added API_VERSION env var), and its server logs show it now serves /v2/stock, so the likely cause is an API path change in inventory that orders-api does not follow.

**Root cause** (medium confidence, `dependency_failure`): orders-api (version 2.3.0, image python:3.12-alpine, revision 1 unchanged) fails at startup with "FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found". The inventory service logs "inventory serving /v2/stock", so the stock endpoint has moved from /stock to /v2/stock. The inventory deployment rolled out revision 2 about 44s before the alert, adding env API_VERSION, which is the most likely change that moved the path. orders-api has not changed (only revision 1, created 2m ago), so the rollout of inventory is the trigger. Confidence is medium because the logs show the path change but not the code that caused it, and the previous instance logs were no longer available.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Pod/orders-api-568b7b8d9f-vzp22, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api previous logs: 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_describe_pod`: orders-api-568b7b8d9f-vzp22 container app: terminated Error, exit_code 1, restarts 3, limits memory 32Mi, no liveness/readiness probes; not OOMKilled
- `kubernetes_recent_changes`: inventory revision 2 rollout 48s ago, env_added API_VERSION; orders-api only revision 1 (created 2m ago), no config change
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l logs: 'inventory serving /v2/stock'
- `kubernetes_describe_deployment`: orders-api: Available False, MinimumReplicasUnavailable, replicas ready 0 of 1; inventory revision 2 ready 1/1
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 ready 0/1, restarts 3, last_terminated Error exit 1

**Recommendations**
1. Confirm the inventory revision 2 change: compare the inventory app code or image between revisions and find why /stock became /v2/stock (API_VERSION likely selects the route).
2. Fastest fix: roll back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders) so /stock is served again, then confirm orders-api stops crashing. This needs human approval.
3. Alternative: update orders-api INVENTORY_URL or its stock path to the new /v2/stock endpoint, if the v2 API is intended. Check the orders-api 2.3.0 expected API version first.
4. After the fix, check that orders-api pod reaches Ready and that the KubePodCrashLooping alert clears. Note that the orders-api pod has no readiness probe.

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
6. `incidents_search` {"keywords": "orders-api crashloop"}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "orders-api"}
8. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l"}
9. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
10. `TriageReport` {"summary": "orders-api pod vzp22 is crash looping (exit 1) because its startup stock sync calls inventory's /stock endpoint and gets HTTP 404. The inventory deployment was rolled out 44s before the alert (revision 2 added API_VERSION env var), and its server logs show it now serves /v2/stock, so th
