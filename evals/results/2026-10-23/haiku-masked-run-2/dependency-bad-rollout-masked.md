## orders-api (pod orders-api-568b7b8d9f-vzp22) is crash looping because its startup stock sync gets HTTP 404 from the inventory service. Inventory was rolled out to revision 2 about 48s before the alert, and its logs show it now serves /v2/stock, so orders-api's /stock call no longer matches. The likely fix is to roll inventory back to revision 1 or point orders-api at /v2/stock, pending approval.

**Root cause** (medium confidence, `bad_rollout`): The inventory deployment rolled out revision 2 (ReplicaSet inventory-b775d96fd, created 44s before the check) that added env API_VERSION. Its app log reads 'inventory serving /v2/stock'. orders-api (single revision 1, unchanged) calls GET http://inventory.orders:8080/stock at startup and gets 'HTTP Error 404: Not Found', so it exits with 'FATAL: stock sync failed' and exit code 1 on each start. Its restarts climb (3 so far) and the deployment is Available=False (MinimumReplicasUnavailable, 0/1 ready). The orders-api image and config did not change, so the inventory rollout is the trigger. The crash is a startup dependency check with no retry.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Pod/orders-api-568b7b8d9f-vzp22, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api previous-instance logs (latest instance shown, earlier logs gone): 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'.
- `kubernetes_describe_pod`: orders-api-568b7b8d9f-vzp22 container app: state Terminated Error exit_code 1, restarts 3, Ready False (ContainersNotReady), no probes configured, env INVENTORY_URL, limits memory 32Mi (not OOMKilled).
- `kubernetes_recent_changes`: inventory revision 2 rollout 48s ago with env_added API_VERSION; orders-api revision 1 created 2m ago with no later change.
- `kubernetes_describe_deployment`: inventory rollout_history: revision 2 (inventory-b775d96fd, 1 replica, env API_VERSION) active, revision 1 (inventory-8469585669) scaled to 0 with no env. Deployment is Available and healthy.
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l app log: 'inventory serving /v2/stock', so the inventory service's stock endpoint is now under /v2/.
- `kubernetes_describe_deployment`: orders-api deployment: 1 desired, 0 ready, Available=False 'MinimumReplicasUnavailable'; only revision 1 exists.

**Recommendations**
1. Ask for approval to roll back the inventory deployment to revision 1 (kubectl rollout undo deployment/inventory -n orders, or set API_VERSION off). This restores the /stock path that orders-api expects. Then confirm orders-api's next start succeeds.
2. Alternatively, if v2 is intended, update orders-api to call /v2/stock (or set its INVENTORY_URL path) and roll it out. Make this the fix only after confirming the new path returns 200.
3. Do not restart orders-api alone; it will keep crashing until the 404 is resolved.
4. Afterwards, consider making the orders-api stock sync retry with backoff instead of exiting on first failure, and check the inventory service's API contract before rolling out path changes.
5. Verify with kubectl get pods -n orders that orders-api is 1/1 Ready and restarts stop increasing.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders", "label_selector": ""}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "container": "app", "previous": true, "tail_lines": 50}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
6. `incidents_search` {"keywords": "orders-api crashloop", "days": 90, "limit": 5}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
8. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "container": "app", "previous": false, "tail_lines": 50}
9. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "orders-api"}
10. `runbooks_read_runbook` {"name": "pod-crashlooping"}
