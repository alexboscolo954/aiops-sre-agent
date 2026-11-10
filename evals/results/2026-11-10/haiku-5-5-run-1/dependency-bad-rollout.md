## orders-api pod is crash looping on startup: its stock sync calls GET http://inventory.orders:8080/stock and gets HTTP 404. The inventory deployment was rolled out 48s before the alert (revision 2 added env API_VERSION), and the orders-api deployment has no revision change, so the likely trigger is the inventory rollout changing or removing the /stock endpoint. This is inferred, not confirmed.

**Root cause** (medium confidence, `dependency_failure`): orders-api (v2.3.0) exits at startup with "FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found". The inventory service is reachable but no longer serves /stock. The only recent change is inventory revision 2 (created 44-48s before the alert), which added env API_VERSION; orders-api itself has only revision 1 and did not change. The rollout of inventory is the strongest lead, but the logs do not show that the 404 began with that rollout, and I did not verify the inventory endpoints directly. Earlier evidence: orders-api had 0/1 ready and restarts=3. The pod also showed FailedScheduling once due to a taint, but it is now scheduled and running.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Pod/orders-api-568b7b8d9f-vzp22, orders/Deployment/inventory

**Evidence**
- `kubernetes_describe_pod`: orders-api-568b7b8d9f-vzp22 container app: state Error, exit_code 1, restarts 3, last_state Error exit 1; limits memory 32Mi, not OOMKilled
- `kubernetes_pod_logs`: previous=true (latest instance shown): 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_recent_changes`: inventory rollout revision 2 at 48s ago, env_added API_VERSION; orders-api only revision 1 (created 2m ago), no change
- `kubernetes_describe_deployment`: orders-api: replicas desired 1 ready 0, Available=False MinimumReplicasUnavailable, single revision 1 with env INVENTORY_URL
- `kubernetes_describe_deployment`: inventory: revision 2 (inventory-b775d96fd) created 44s ago is Available and ready 1/1; revision 1 scaled to 0

**Recommendations**
1. Check the inventory service's /stock endpoint directly (for example, curl from inside the orders namespace) to confirm it returns 404 now.
2. Compare inventory revision 1 and revision 2 for changed routes or paths, and the API_VERSION setting (for example, a versioned path such as /v2/stock).
3. If the inventory rollout removed or moved /stock, roll back inventory to revision 1 (kubectl rollout undo) with human approval, or fix the orders-api URL or contract to match the new endpoint.
4. Do not restart orders-api alone; the crash is deterministic on the 404 and a restart will not fix it.
5. Once inventory serves /stock again, orders-api should start on its next restart; confirm it reaches 1/1 ready.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "orders-api"}
6. `incidents_search` {"keywords": "orders-api crashloop INVENTORY_URL"}
7. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
8. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
9. `TriageReport` {"summary": "orders-api pod is crash looping on startup: its stock sync calls GET http://inventory.orders:8080/stock and gets HTTP 404. The inventory deployment was rolled out 48s before the alert (revision 2 added env API_VERSION), and the orders-api deployment has no revision change, so the likely
