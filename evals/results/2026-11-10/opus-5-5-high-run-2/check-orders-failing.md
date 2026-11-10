## orders-api has 0 of 1 replicas ready. Its pod crash loops because its startup stock sync gets HTTP 404 from inventory at /stock. The 404 started after inventory's revision 2 rollout about 48s ago, which only serves /v2/stock.

**Root cause** (high confidence, `bad_rollout`): inventory revision 2 (ReplicaSet inventory-b775d96fd, created 44s ago) added the env var API_VERSION, and the new pod logs 'inventory serving /v2/stock'. Revision 1 had no env vars. orders-api 2.3.0 still calls GET http://inventory.orders:8080/stock at startup, gets 'HTTP Error 404: Not Found', logs FATAL and exits with code 1, so it lands in CrashLoopBackOff. This is an incompatible API path change in a dependency's rollout. That inference rests on the timing and the logs: the old revision's logs are gone, so I can't directly confirm it served /stock.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l: 'inventory serving /v2/stock'
- `kubernetes_recent_changes`: inventory rollout to revision 2 about 48s ago added env var API_VERSION; orders-api has not changed since it was created about 2m ago
- `kubernetes_describe_deployment`: inventory rev 2 (inventory-b775d96fd, 44s) has env [API_VERSION]; rev 1 (inventory-8469585669, 2m, now 0 replicas) had no env vars
- `kubernetes_describe_pod`: orders-api container app has 3 restarts, Warning BackOff restarting failed container, and Ready=False ContainersNotReady
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 is 0/1 ready with 3 restarts and exit_code 1 (Error)

**Recommendations**
1. Roll inventory back to revision 1 (kubectl -n orders rollout undo deployment/inventory), or remove API_VERSION so it serves /stock again.
2. Once inventory serves /stock, check that orders-api's pod starts its stock sync and becomes ready. Restart the pod if it is still waiting in back-off.
3. Long-term, coordinate the inventory API version change with orders-api. Either point orders-api's INVENTORY_URL or client at /v2/stock, or have inventory serve both paths during the migration.

Runbook: `deployment-unavailable`

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "tail_lines": 50}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
7. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 50}
8. `incidents_search` {"keywords": "orders-api inventory 404 stock"}
9. `runbooks_runbook_for_alert` {"alertname": "KubeDeploymentReplicasMismatch"}
