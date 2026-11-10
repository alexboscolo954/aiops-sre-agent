## inventory revision 2 changed its stock endpoint to /v2/stock. orders-api still calls /stock, gets a 404 at startup and exits, so orders-api is crash-looping with 0/1 replicas available.

**Root cause** (high confidence, `bad_rollout`): inventory revision 2 (rolled out 48s ago, added env var API_VERSION) now serves only /v2/stock ('inventory serving /v2/stock'). orders-api 2.3.0 calls GET http://inventory.orders:8080/stock at startup, gets HTTP 404 Not Found and exits with code 1. That has happened 3 times, leaving the pod in CrashLoopBackOff. The Hub saw nothing failing just before the change.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago and added the env var API_VERSION.
- `kubernetes_pod_logs`: orders-api: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'. inventory: 'inventory serving /v2/stock'.
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 is 0/1 with 3 restarts, terminated Error exit 1.
- `kubernetes_list_deployments`: orders-api is 0/1 with MinimumReplicasUnavailable.
- `kubernetes_get_events`: BackOff restarting failed container app in orders-api pod (count 3).
- `runbooks_read_runbook`: pod-crashlooping runbook: if a new revision caused the crash, roll back that revision; a restart does not fix a crash loop.

**Recommendations**
1. Roll back inventory to revision 1, or set API_VERSION so it serves /stock again, until orders-api supports /v2/stock. Use kubectl -n orders rollout undo deployment/inventory --to-revision=1.
2. After the rollback, check that orders-api comes up 1/1 and its logs no longer show the 404.
3. Coordinate the API change: update orders-api's INVENTORY_URL or its client to /v2/stock, or have inventory serve both paths, before rolling out inventory revision 2 again.
4. Don't restart orders-api; restarting won't stop the crash loop while inventory still returns 404 on /stock.

Runbook: `pod-crashlooping`

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "tail_lines": 50}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 50}
6. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
7. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
8. `incidents_search` {"keywords": "orders-api inventory"}
9. `runbooks_search_runbooks` {"keywords": "crashloop dependency rollout"}
10. `runbooks_read_runbook` {"name": "pod-crashlooping"}
