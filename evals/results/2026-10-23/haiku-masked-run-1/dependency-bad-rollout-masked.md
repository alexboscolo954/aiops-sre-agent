## orders-api (v2.3.0) exits on startup because its stock sync gets HTTP 404 from inventory at /stock. Inventory was rolled out to revision 2 about 48s before the alert, adding an API_VERSION env var, and its log now says it serves /v2/stock. The likely cause is the inventory rollout changing the API path that orders-api still calls.

**Root cause** (medium confidence, `bad_rollout`): The inventory deployment rolled out revision 2 (replicaset inventory-b775d96fd, created 44s before triage) which added env API_VERSION to the app container. Its current log reads 'inventory serving /v2/stock', while orders-api (revision 1, unchanged, env INVENTORY_URL only) fails at startup with 'FATAL: stock sync failed: GET http://<host>:8080/stock: HTTP Error 404: Not Found'. orders-api has no startup retry, so it exits with code 1 on each attempt (restarts 3, 0/1 ready, deployment Available=False). The path mismatch is inferred from the two logs and the rollout diff, not confirmed by a direct inventory request, so confidence is medium.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Pod/orders-api-568b7b8d9f-vzp22, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api previous/latest run: 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l (new revision 2) log: 'inventory serving /v2/stock'
- `kubernetes_recent_changes`: inventory revision 2 rollout 48s ago with env_added API_VERSION; inventory revision 1 created 2m ago; orders-api revision 1 created 2m ago, no later change
- `kubernetes_describe_pod`: orders-api-568b7b8d9f-vzp22: container app state Error exit_code 1, restarts 3, Ready False (ContainersNotReady), no liveness or readiness probes, limits memory 32Mi
- `kubernetes_describe_deployment`: inventory rollout_history: revision 2 (inventory-b775d96fd, env API_VERSION) replicas 1; revision 1 (inventory-8469585669) scaled to 0. orders-api: Available False, MinimumReplicasUnavailable

**Recommendations**
1. Confirm the inventory API path: check the INVENTORY_URL value on orders-api and the API_VERSION value on inventory revision 2, and whether /stock is still served.
2. Roll back the inventory deployment to revision 1 (kubectl rollout undo deployment/inventory -n orders). This needs human approval. It restores /stock, which orders-api depends on.
3. Alternatively, if v2 is intended, update orders-api's INVENTORY_URL to the /v2/stock path. This is a config change and also needs approval.
4. After the fix, confirm orders-api-568b7b8d9f-vzp22 (or its replacement) reaches 1/1 Ready and the restart count stops increasing.
5. Add a startup retry or a readiness check in orders-api so a dependency's brief unavailability does not crash-loop it.

Runbook: `pod-crashlooping`

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders", "label_selector": ""}
2. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "container": "app", "tail_lines": 50, "previous": true}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
6. `incidents_search` {"keywords": "orders-api crashloop", "days": 90, "limit": 5}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
8. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "container": "app", "tail_lines": 50, "previous": false}
9. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "orders-api"}
10. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders", "label_selector": ""}
