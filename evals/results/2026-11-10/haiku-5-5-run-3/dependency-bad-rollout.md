## orders-api pod is crash looping because its startup stock sync gets HTTP 404 from inventory.orders:8080/stock. The inventory deployment was rolled out to revision 2 about 48s before the alert, adding an API_VERSION env var, which is the likely trigger. Rolling back inventory to revision 1 is the recommended fix, pending confirmation that the 404 is caused by the rollout.

**Root cause** (medium confidence, `bad_rollout`): orders-api (v2.3.0) exits at startup with "FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404". It depends on the inventory service, which was rolled out to revision 2 (~44-48s before the alert, adding env API_VERSION; revision 1 had none). Inventory is Available and 1/1 ready, so the 404 is an endpoint/contract mismatch and not a dead service. The rollout is the only recent change, so it is the most likely trigger. The logs do not show what inventory serves on /stock, so this is inferred. orders-api itself has no recent change (revision 1, created 2m ago alongside inventory's revision 1).
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Pod/orders-api-568b7b8d9f-vzp22, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api previous/latest instance: 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_describe_pod`: container app state Error exit_code 1, restarts 3, Ready False; limits 32Mi memory, no OOMKilled reason
- `kubernetes_recent_changes`: inventory revision 2 rollout 48s ago, diff env_added app: [API_VERSION]; no other rollouts in orders namespace except creation of revision 1 for both deployments 2m ago
- `kubernetes_describe_deployment`: inventory: revision 2 (inventory-b775d96fd) is current, Available True, 1/1 ready; revision 1 (inventory-8469585669) scaled to 0 replicas
- `kubernetes_list_deployments`: orders-api ready 0/1, condition Available False MinimumReplicasUnavailable

**Recommendations**
1. Check inventory's /stock endpoint directly (e.g. curl from a pod in the orders namespace) and its logs for requests returning 404; confirm whether the API_VERSION change altered the route or path.
2. If the rollout is confirmed as the cause, roll back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders), which requires human approval.
3. Once inventory serves /stock again, orders-api should recover on its next restart; verify orders-api reaches Ready.
4. If the 404 is a stale orders-api config (orders-api expects a different path), fix the config in orders-api instead of rolling back inventory.
5. Consider making orders-api retry the stock sync at startup rather than exiting on the first failure.

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true}
5. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
6. `incidents_search` {"keywords": "orders-api crashloop"}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
8. `TriageReport` {"summary": "orders-api pod is crash looping because its startup stock sync gets HTTP 404 from inventory.orders:8080/stock. The inventory deployment was rolled out to revision 2 about 48s before the alert, adding an API_VERSION env var, which is the likely trigger. Rolling back inventory to revision
