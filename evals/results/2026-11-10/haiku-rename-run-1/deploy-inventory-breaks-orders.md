## orders-api is crash-looping (0/1 ready, 3 restarts) because its stock sync gets HTTP 404 from inventory, which after the revision 2 rollout serves /v2/stock. The inventory rollout is the trigger, and inventory itself is healthy.

**Root cause** (high confidence, `bad_rollout`): The inventory revision 2 rollout added env API_VERSION and now serves /v2/stock (inventory pod logs). orders-api 2.3.0 still calls http://inventory.orders:8080/stock and gets HTTP 404 (orders-api logs), exits with code 1 and goes into BackOff. orders-api was not changed, so the inventory rollout is the cause. The link between API_VERSION and the /v2 path is inferred, not shown directly.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api: FATAL stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found
- `kubernetes_pod_logs`: inventory: inventory serving /v2/stock
- `kubernetes_recent_changes`: inventory revision 2 rollout 48s ago, env_added API_VERSION
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 0/1, restarts 3, exit code 1

**Recommendations**
1. Roll back orders/inventory to revision 1 (the change is an env-only rollout), or else point orders-api at /v2/stock if v2 is intended. Either fix needs a human decision and approval.
2. After the rollback or fix, confirm orders-api reaches 1/1 ready with no new restarts and no BackOff events.
3. Check the inventory readiness probe 'connection refused' warnings from the rollout (44s and 47s ago) and confirm they have stopped.
4. Check orders-api's compatibility with the inventory API version before shipping API_VERSION again.

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders", "label_selector": ""}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders", "warnings_only": true}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "container": "app", "tail_lines": 50, "previous": false}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "container": "app", "tail_lines": 50, "previous": false}
6. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
8. `incidents_search` {"keywords": "orders-api inventory stock 404", "days": 90, "limit": 5}
9. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
