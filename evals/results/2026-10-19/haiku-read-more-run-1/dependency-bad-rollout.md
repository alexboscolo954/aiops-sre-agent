## orders-api is crash looping because its startup stock sync calls http://inventory.orders:8080/stock and gets a 404. The inventory deployment was rolled out to revision 2 about 48s before the alert, adding API_VERSION, and its log now reports it is serving /v2/stock, so the likely fault is the inventory rollout moving the endpoint path. orders-api itself was not changed.

**Root cause** (medium confidence, `bad_rollout`): inventory revision 2 (ReplicaSet inventory-b775d96fd, created 44s before triage, adding env API_VERSION) is serving /v2/stock, while orders-api 2.3.0 requests /stock. orders-api logs 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found' and exits with code 1 at startup, so it restarts with back-off (3 restarts, 0/1 ready). Revision 1 of inventory (created 2m ago) was the working version. The orders-api deployment has a single revision, so the break comes from the inventory side. The link between the path change and the 404 is inferred from the logs, not confirmed by a diff of the inventory code or config.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Pod/orders-api-568b7b8d9f-vzp22, orders/Deployment/inventory

**Evidence**
- `kubernetes_describe_pod`: orders-api-568b7b8d9f-vzp22 container app: terminated Error, exit_code 1, restarts 3, Ready False (ContainersNotReady); BackOff events for restarting failed container app; no liveness or readiness probes.
- `kubernetes_pod_logs`: previous=true for orders-api-568b7b8d9f-vzp22 (latest instance shown): 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'.
- `kubernetes_recent_changes`: orders/inventory rollout to revision 2 at 48s, env_added API_VERSION. Revision 1 and orders-api revision 1 were both created 2m ago, so orders-api has not changed since its initial deploy.
- `kubernetes_describe_deployment`: inventory rollout_history: revision 2 (replicaset inventory-b775d96fd, created 44s, 1 replica) replaced revision 1 (inventory-8469585669, scaled to 0). Available True, MinimumReplicasAvailable.
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l (revision 2, running, 0 restarts) logs: 'inventory serving /v2/stock'.
- `kubernetes_list_deployments`: orders-api ready 0/1, problem Available False MinimumReplicasUnavailable; inventory ready 1/1 with no problems.

**Recommendations**
1. Roll back the inventory deployment to revision 1 (kubectl rollout undo deployment/inventory -n orders), which was serving /stock, so orders-api can start. This needs human approval before it is run.
2. Alternatively, fix orders-api's stock URL to /v2/stock, or add an API_VERSION-aware path, and release a new orders-api revision. Confirm the intended inventory API contract first.
3. After the fix, check that orders-api-568b7b8d9f-vzp22 reaches 1/1 Ready and that restarts stop increasing.
4. Add a readiness probe and a startup-dependency check to orders-api, or make the stock sync retry, so one failing dependency doesn't crash-loop the pod.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_describe_pod`
3. `kubernetes_recent_changes`
4. `kubernetes_pod_logs`
5. `kubernetes_list_deployments`
6. `kubernetes_describe_deployment`
7. `kubernetes_list_pods`
8. `kubernetes_pod_logs`
