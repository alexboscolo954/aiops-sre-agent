## orders-api is crash looping because its startup stock sync calls inventory's /stock endpoint and gets HTTP 404. The inventory deployment was rolled out 48 seconds before triage (revision 2, adding API_VERSION env var), and its log now says it serves /v2/stock. The orders-api pod itself was not changed.

**Root cause** (medium confidence, `bad_rollout`): Inventory revision 2 (ReplicaSet inventory-b775d96fd, rolled out about 48s before triage) added the env var API_VERSION to the inventory container. Its current log reads "inventory serving /v2/stock". orders-api (revision 1, unchanged, image python:3.12-alpine) fails at startup with "FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found" and exits with code 1. The restart count is 3 and the back-off is growing. The crash is an inferred dependency break: the 404 proves the path is gone, and the timing with the inventory rollout points to it. The exact mechanism by which API_VERSION changes the route is not visible in the evidence.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Pod/orders-api-568b7b8d9f-vzp22, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22 (container app, current instance): "orders-api starting, version 2.3.0" then "FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found".
- `kubernetes_describe_pod`: orders-api-568b7b8d9f-vzp22: container app state Error, exit_code 1, restarts 3, Ready False (ContainersNotReady). No liveness or readiness probes. Image python:3.12-alpine.
- `kubernetes_recent_changes`: orders/inventory revision 2 rollout 48s ago with env_added app: [API_VERSION]. orders/orders-api only has revision 1 (created 2m ago, no diff).
- `kubernetes_describe_deployment`: inventory rollout_history: revision 2 (replicaset inventory-b775d96fd, created 44s ago, env [API_VERSION]); revision 1 (replicaset inventory-8469585669, replicas 0, env []). Deployment is Available, 1/1 ready.
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l (container app, current log): "inventory serving /v2/stock".

**Recommendations**
1. Roll back the inventory deployment to revision 1 (kubectl -n orders rollout undo deployment/inventory). This needs human approval. It restores the /stock path that orders-api expects, so orders-api should start cleanly.
2. Alternatively, if v2 is intended, fix orders-api to call /v2/stock or set its inventory base URL and API version to match, then roll it out. Confirm which API version orders-api 2.3.0 supports first.
3. After the fix, confirm orders-api-568b7b8d9f-vzp22 (or its replacement) reaches 1/1 Ready and restarts stop increasing. Check that the inventory /stock path returns 200.
4. Add a readiness or startup check to orders-api, and add a contract check on inventory's API routes to the inventory release process, so a breaking route change is caught before rollout.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_recent_changes`
4. `kubernetes_pod_logs`
5. `kubernetes_describe_pod`
6. `kubernetes_describe_deployment`
7. `kubernetes_pod_logs`
8. `runbooks_read_runbook`
