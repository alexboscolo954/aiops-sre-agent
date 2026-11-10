## orders-api is crash looping (0/1 ready) because its startup stock sync gets a 404 from inventory. This started after the inventory rollout to revision 2 about 48s ago, after which inventory serves only /v2/stock.

**Root cause** (high confidence, `bad_rollout`): inventory revision 2 (ReplicaSet inventory-b775d96fd, created 44s ago) added the API_VERSION env var. inventory now logs 'inventory serving /v2/stock'. orders-api 2.3.0 still calls GET http://inventory.orders:8080/stock, gets HTTP 404 and exits with FATAL (exit code 1), so it never becomes ready. orders-api has 3 restarts on a 2m-old pod while inventory rev 2 is only about 48s old, so I can't rule out earlier failures before rev 2. Still, the current failure is the 404 on the path that rev 2 changed.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22: 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l: 'inventory serving /v2/stock'
- `kubernetes_recent_changes`: inventory rollout to revision 2 about 48s ago, diff env_added app: [API_VERSION]; orders-api created 2m ago with no later changes
- `kubernetes_describe_deployment`: inventory rev 2 (inventory-b775d96fd, 44s) has env API_VERSION; rev 1 (inventory-8469585669, 2m) had no env, now scaled to 0
- `kubernetes_list_pods`: orders-api pod is 0/1 ready, 3 restarts, last terminated Error exit 1

**Recommendations**
1. Roll back inventory to revision 1 (for example `kubectl rollout undo deployment/inventory -n orders --to-revision=1`) or remove or fix API_VERSION so inventory serves /stock again.
2. Once inventory serves /stock, confirm that orders-api restarts on its own and reaches 1/1 ready.
3. Long term, either update orders-api to call /v2/stock or have inventory keep serving /stock for older clients. Add retry or backoff to orders-api's startup stock sync.
4. Don't just restart orders-api: per the runbook, a restart doesn't fix a crash loop.

Runbook: `pod-crashlooping`

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "tail_lines": 50}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 50}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
8. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
