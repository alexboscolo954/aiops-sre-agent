## Inventory revision 2 is running with 1/1 ready, but the change broke the dependent orders-api. Its unchanged v2.3.0 pod now crash-loops because the inventory service returns 404 on /stock, which the inventory app serves as /v2/stock. The Check fails on the new orders-api failures and the new warning events.

**Root cause** (high confidence, `bad_rollout`): The inventory rollout to revision 2 (added env API_VERSION, 48s before the check) changed the served path to /v2/stock. orders-api (version 2.3.0, revision 1, unchanged) still calls http://inventory.orders:8080/stock and gets HTTP 404, so it exits at startup with FATAL and crash-loops (3 restarts, 0/1 ready). The inventory readiness probe also failed once on connection refused during startup, though the pod is now Ready.
**Severity:** high  ·  **Affected:** orders/deployment/inventory, orders/deployment/orders-api

**Evidence**
- `kubernetes_recent_changes`: inventory revision 2 rollout 48s ago, diff env_added app: [API_VERSION]; orders-api has only revision 1.
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'.
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l: 'inventory serving /v2/stock'.
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22: 0/1 ready, 3 restarts, last terminated Error exit 1; inventory-b775d96fd-qq86l 1/1, 0 restarts.
- `kubernetes_get_events`: Warning BackOff orders-api pod (count 3); Warning Unhealthy inventory readiness probe connection refused (44s ago).
- `kubernetes_describe_deployment`: orders-api Available=False, MinimumReplicasUnavailable; inventory Available=True, 1/1 ready on revision 2.

**Recommendations**
1. Confirm the intended inventory API path. Either roll back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders) or fix the path that orders-api calls (/v2/stock versus /stock).
2. Once orders-api can reach /stock, verify orders-api is 1/1 ready with no further restarts.
3. Check the inventory readiness probe path and timing, since it failed with connection refused during startup.

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 30}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders", "warnings_only": true}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l"}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "orders-api"}
8. `incidents_search` {"keywords": "inventory orders-api"}
9. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
10. `CheckResult` {"passed": false, "summary": "The inventory rollout (revision 2, which added API_VERSION env) is not healthy. Its pod is Ready 1/1 with 0 restarts, but the readiness probe failed at startup and its serving path changed: orders-api, which did not change, now crash-loops (3 restarts, 0/1 ready) with \
