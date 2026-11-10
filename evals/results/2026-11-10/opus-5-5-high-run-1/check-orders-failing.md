## orders-api (0/1 ready) is crash-looping because its startup stock sync gets a 404 from inventory. About 48s ago inventory revision 2 added API_VERSION, and inventory now serves only /v2/stock instead of /stock.

**Root cause** (high confidence, `bad_rollout`): inventory revision 2 (ReplicaSet inventory-b775d96fd, created 44s ago) added the env var API_VERSION, which revision 1 did not have. The new inventory pod logs 'inventory serving /v2/stock'. orders-api 2.3.0 still calls GET http://inventory.orders:8080/stock at startup, gets HTTP 404 and exits with code 1 ('FATAL: stock sync failed'). That leaves it in BackOff with 3 restarts and 0/1 ready. orders-api itself has not changed since it was created (revision 1). The pod's earlier FailedScheduling taint event was 2m ago and has cleared, since the pod is scheduled and running.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_list_deployments`: orders-api ready 0/1, MinimumReplicasUnavailable; inventory 1/1
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l: 'inventory serving /v2/stock'
- `kubernetes_recent_changes`: 48s ago inventory rollout to revision 2 with env_added API_VERSION; orders-api has not changed since it was created (revision 1)
- `kubernetes_describe_deployment`: inventory revision 2 (inventory-b775d96fd) has env API_VERSION; revision 1 (inventory-8469585669) had no env and is scaled to 0
- `kubernetes_describe_pod`: orders-api app container exit_code 1, restarts 3, Warning BackOff 'Back-off restarting failed container app'; env INVENTORY_URL; no probes

**Recommendations**
1. Roll back inventory to revision 1 (e.g. kubectl -n orders rollout undo deployment/inventory --to-revision=1), or remove API_VERSION, so that /stock is served again.
2. Check that orders-api recovers by itself on its next backoff restart and reaches 1/1. If it is stuck in a long backoff, delete the pod.
3. Long term, put the API version change behind backward compatibility: have inventory serve both /stock and /v2/stock, or update orders-api's INVENTORY_URL or path before switching inventory to v2.
4. Don't scale or restart orders-api as the fix. It will keep failing while inventory answers /stock with 404.

Runbook: `deployment-unavailable`

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
6. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
8. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l"}
9. `runbooks_runbook_for_alert` {"alertname": "KubeDeploymentReplicasMismatch"}
