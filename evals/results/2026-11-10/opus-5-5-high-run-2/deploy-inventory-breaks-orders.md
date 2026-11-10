## orders-api is crash looping (0/1 ready, 3 restarts) since inventory revision 2 rolled out. The new inventory serves only /v2/stock, so orders-api's startup call to /stock gets HTTP 404 and the process exits with code 1.

**Root cause** (high confidence, `bad_rollout`): inventory revision 2, rolled out 48s ago, added the env var API_VERSION. inventory now logs 'inventory serving /v2/stock'. orders-api 2.3.0 has not changed (revision 1). At startup it calls GET http://inventory.orders:8080/stock, gets HTTP 404 Not Found, logs a FATAL 'stock sync failed' error and exits with code 1. The Hub saw nothing failing just before the change, and the first crash came after the rollout, so the inventory change broke a dependent workload.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_recent_changes`: inventory revision 2, 48s ago: env_added API_VERSION on container app. No change to orders-api.
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'. inventory-b775d96fd-qq86l: 'inventory serving /v2/stock'.
- `kubernetes_describe_pod`: orders-api container app: terminated with Error, exit code 1, 3 restarts. Its only env var is INVENTORY_URL. Back-off restarting failed container.
- `kubernetes_list_deployments`: orders-api is 0/1 ready (MinimumReplicasUnavailable). inventory is 1/1 ready.
- `kubernetes_get_events`: BackOff warning for Pod/orders-api-568b7b8d9f-vzp22, count 3, last seen 3s ago.

**Recommendations**
1. Roll inventory back to revision 1, or remove the API_VERSION setting, so it serves /stock again. Then confirm that orders-api starts and becomes 1/1 ready.
2. Before rolling inventory's v2 API out again, either make it keep serving the old /stock path, or update orders-api (through INVENTORY_URL or code) to call /v2/stock and release that first.
3. Don't restart orders-api as a fix: it will keep crashing until inventory serves /stock again.

Runbook: `pod-crashlooping`

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
4. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "tail_lines": 50}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "tail_lines": 50}
7. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
8. `incidents_search` {"keywords": "orders-api inventory"}
9. `runbooks_search_runbooks` {"keywords": "crashloop dependency rollout"}
10. `runbooks_read_runbook` {"name": "pod-crashlooping"}
