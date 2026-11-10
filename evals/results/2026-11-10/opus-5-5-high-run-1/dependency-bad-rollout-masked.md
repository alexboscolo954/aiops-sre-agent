## orders-api (pod orders-api-568b7b8d9f-vzp22) is crash looping: it exits with code 1 at startup because GET http://inventory.orders:8080/stock returns 404. Its dependency inventory rolled out revision 2 about 48s ago. That revision added the env var API_VERSION, and inventory now serves only /v2/stock.

**Root cause** (high confidence, `bad_rollout`): Inventory revision 2 (ReplicaSet inventory-b775d96fd, created 44s ago) added the API_VERSION env var, which revision 1 did not have. The new inventory pod logs 'inventory serving /v2/stock', so the unversioned /stock path is gone. orders-api 2.3.0 still calls GET http://inventory.orders:8080/stock during startup stock sync. It gets HTTP 404 and exits with 'FATAL: stock sync failed' (exit code 1, 3 restarts so far). One caveat: the orders-api pod finished pulling its image only 48s ago, which is when inventory rev 2 rolled out, so it probably never ran against rev 1. I am inferring that rev 1 served /stock from the env diff, not from rev 1 logs.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22: 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 is 0/1 ready with 3 restarts, last terminated Error exit_code 1 (not OOM). inventory-b775d96fd-qq86l is Running 1/1, age 44s
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago, diff env_added app: [API_VERSION]. orders-api has only revision 1 (created 2m ago)
- `kubernetes_describe_deployment`: inventory rev 2 (inventory-b775d96fd) env [API_VERSION], rev 1 (inventory-8469585669) env [] and scaled to 0
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l logs: 'inventory serving /v2/stock'
- `kubernetes_describe_pod`: orders-api container has env INVENTORY_URL, no probes, and BackOff events 'Back-off restarting failed container app'

**Recommendations**
1. Roll back inventory to revision 1 (kubectl -n orders rollout undo deployment/inventory --to-revision=1) or remove API_VERSION, so the /stock path comes back. This needs human approval.
2. Watch orders-api-568b7b8d9f-vzp22 recover by itself on its next backoff restart once /stock answers. A restart alone does not fix it while inventory serves only /v2/stock.
3. To move to v2 later, update orders-api so its INVENTORY_URL/path uses /v2/stock, or have inventory serve both /stock and /v2/stock, then roll inventory forward again.
4. Make orders-api handle a failed stock sync at startup (retry/backoff instead of a FATAL exit), and add a readiness probe.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true}
5. `kubernetes_recent_changes` {"cluster": "kind"}
6. `incidents_search` {"keywords": "orders-api crash loop"}
7. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l"}
8. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
