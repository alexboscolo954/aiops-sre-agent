## orders-api (0/1 ready) keeps crashing at startup. Its stock sync to inventory gets a 404 because inventory revision 2, rolled out 48s before this check and adding the API_VERSION env var, now serves /v2/stock where orders-api still requests /stock.

**Root cause** (high confidence, `bad_rollout`): Inventory was rolled out to revision 2 48s before this check. The only change was a new API_VERSION env var, and inventory's logs now say 'inventory serving /v2/stock'. orders-api (revision 1, version 2.3.0) calls GET http://inventory.orders:8080/stock at startup, gets 'HTTP Error 404: Not Found', logs FATAL and exits with code 1, so it keeps restarting. Inventory's revision 1 had no env vars, and orders-api is unchanged since it was created.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api pod: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'. The previous run's logs were gone, so this is the latest run.
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l: 'inventory serving /v2/stock'
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago, adding the env var API_VERSION; orders-api has had only revision 1 (created 2m ago)
- `kubernetes_describe_deployment`: inventory revision 2 (inventory-b775d96fd) has env [API_VERSION]; revision 1 (inventory-8469585669) had no env vars and is scaled to 0
- `kubernetes_list_pods`: orders-api pod has 3 restarts and terminated with Error exit 1

**Recommendations**
1. Roll inventory back to revision 1 (kubectl rollout undo deployment/inventory -n orders), or remove API_VERSION so it serves /stock again. This needs Operator approval.
2. Then confirm orders-api becomes 1/1 ready. If it is still in back-off, it should recover on its next restart attempt.
3. Longer term: change orders-api to call the /v2/stock endpoint before inventory switches to v2, or have inventory serve both paths during the migration. Also make orders-api's startup sync retry instead of exiting on a dependency error.

Runbook: `pod-crashlooping`

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 50}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 50}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
8. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
