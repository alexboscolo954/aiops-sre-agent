## orders-api pod orders-api-568b7b8d9f-vzp22 is crash looping because its startup stock sync gets HTTP 404 from inventory.orders:8080/stock. The inventory deployment rolled out revision 2 about 48s before the alert, adding API_VERSION and serving /v2/stock, so the likely cause is that rollout breaking the orders-api dependency.

**Root cause** (medium confidence, `bad_rollout`): orders-api (v2.3.0, revision 1, created 2m ago, unchanged) exits at startup with "FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found", so it restarts repeatedly (restarts 3, last exit code 1, Error). Inventory rolled out revision 2 (replicaset inventory-b775d96fd, 44s old) which added env API_VERSION to the app container, and its current log reads "inventory serving /v2/stock". The /stock path orders-api calls is therefore no longer served by the new inventory revision. The inventory rollout is the most likely cause, but the link between API_VERSION and the path change is inferred from the logs, not confirmed from the inventory source.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Pod/orders-api-568b7b8d9f-vzp22, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api previous-instance logs (latest instance shown): "orders-api starting, version 2.3.0" then "FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found".
- `kubernetes_describe_pod`: orders-api-568b7b8d9f-vzp22: container app terminated Error, exit_code 1, restarts 3, Ready False (ContainersNotReady), no readiness or liveness probe, BackOff event on the container.
- `kubernetes_recent_changes`: orders/inventory revision 2 rollout 48s ago with env_added app: [API_VERSION]; orders/orders-api revision 1 created 2m ago with no diff.
- `kubernetes_describe_deployment`: inventory rollout_history: revision 2 (inventory-b775d96fd, created 44s, env [API_VERSION]) replaces revision 1 (inventory-8469585669, env [], now 0 replicas); deployment is Available with 1/1 ready.
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l (current instance, running 44s, 0 restarts): "inventory serving /v2/stock".
- `kubernetes_list_pods`: inventory-b775d96fd-qq86l is Running 1/1 with 0 restarts; orders-api-568b7b8d9f-vzp22 is 0/1 with 3 restarts.

**Recommendations**
1. Roll back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders, or the equivalent via the deployment tooling). This is a change and needs human approval. It should restore /stock and let orders-api start.
2. Alternatively, if v2 is intended, update orders-api to call /v2/stock (or set its config to match) and roll that out. Confirm first which API version inventory revision 2 is meant to serve.
3. After the fix, confirm orders-api-568b7b8d9f-vzp22 (or its replacement) reaches 1/1 Ready and that the KubePodCrashLooping alert clears.
4. Consider adding a readiness probe and a startup retry for the stock sync in orders-api, so a dependency outage does not turn into a crash loop.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders", "label_selector": ""}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "container": "app", "tail_lines": 50, "previous": true}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
6. `incidents_search` {"keywords": "orders-api crashloop", "days": 90, "limit": 5}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
8. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l", "container": "app", "tail_lines": 50, "previous": false}
