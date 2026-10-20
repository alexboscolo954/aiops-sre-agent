## orders-api (v2.3.0) is crash looping with exit 1 because its startup stock sync gets HTTP 404 from inventory.orders:8080/stock. The inventory deployment was rolled out to revision 2 about 48 seconds before the alert, and its current log says it now serves /v2/stock, so the rollout most likely moved the endpoint orders-api calls.

**Root cause** (medium confidence, `bad_rollout`): The alerting workload fails at startup: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found', with exit code 1 and restarts=3. The dependency changed in the same window. inventory revision 2 (ReplicaSet inventory-b775d96fd, created 44s before the check) added env API_VERSION and rolled out over revision 1 (created 2m before). Its current log reads 'inventory serving /v2/stock', so the path orders-api requests no longer exists. orders-api itself has not changed (its only revision is 1, created 2m ago), which points at the inventory rollout. The link between API_VERSION and the /v2 path is inferred from the logs, not confirmed in the inventory code or config. Node scheduling and image pulls were not the problem: the pod is scheduled and the image is present.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Pod/orders-api-568b7b8d9f-vzp22, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api previous=true logs (latest instance): 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_describe_pod`: orders-api-568b7b8d9f-vzp22: container app terminated Error, exit_code 1, restarts 3, Ready False, limits memory 32Mi with no OOM reason; events show BackOff restarting failed container
- `kubernetes_recent_changes`: orders/inventory revision 2 rollout 48s ago, env_added API_VERSION; orders/orders-api revision 1 only (created 2m ago, no diff)
- `kubernetes_describe_deployment`: inventory rollout_history: revision 2 (inventory-b775d96fd, created 44s, env [API_VERSION]) replaces revision 1 (inventory-8469585669, env []); orders-api Available=False MinimumReplicasUnavailable
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l (current, running 44s): 'inventory serving /v2/stock'
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 ready 0/1, restarts 3, last terminated Error exit 1; inventory-b775d96fd-qq86l 1/1 Running, 0 restarts

**Recommendations**
1. Ask a human to approve rolling back the orders/inventory deployment to revision 1 (kubectl rollout undo, or helm rollback if managed by Helm). This restores the /stock endpoint that orders-api expects, and orders-api should then start on its next restart.
2. Alternatively, if inventory v2 is intended, fix orders-api's INVENTORY_URL or code to call /v2/stock and release a new orders-api revision. Confirm first which API version orders-api 2.3.0 supports.
3. Confirm the cause by checking the inventory revision 2 change: whether API_VERSION switches the served route from /stock to /v2/stock, and whether inventory revision 1 still serves /stock.
4. Do not restart orders-api alone; it will keep failing at the same startup check until the endpoint or the inventory revision is fixed.
5. After the fix, verify orders-api reaches 1/1 Ready and that the deployment's Available condition is True.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders", "label_selector": ""}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "container": "app", "previous": true, "tail_lines": 50}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
6. `incidents_search` {"keywords": "orders-api crashloop", "days": 90, "limit": 5}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
8. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "orders-api"}
9. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "container": "app", "previous": false, "tail_lines": 50}
10. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
