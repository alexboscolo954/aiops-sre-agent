## orders-api is crash looping because its startup stock sync gets HTTP 404 from inventory.orders:8080/stock. The inventory deployment rolled out revision 2 about 48s before the alert, adding an API_VERSION env var. Its log now says it serves /v2/stock, so the path orders-api calls no longer exists.

**Root cause** (high confidence, `bad_rollout`): Inventory revision 2 (replicaset inventory-b775d96fd, added env API_VERSION) moved the stock endpoint to /v2/stock. orders-api 2.3.0 still calls GET /stock at startup, gets 404, and exits with code 1 because its startup sync has no retry. The crash loop follows from that.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Pod/orders-api-568b7b8d9f-vzp22, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs (orders-api previous instance, tail 100)`: "orders-api starting, version 2.3.0" then "FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found". The previous logs were gone, so this is the latest instance's log, which shows the same crash.
- `kubernetes_describe_pod (orders-api-568b7b8d9f-vzp22)`: Container app: terminated Error, exit_code 1, restarts 3, last_state Error exit 1. Readiness is False with ContainersNotReady. Limits are 32Mi memory, so this is not OOM.
- `kubernetes_recent_changes`: inventory rollout revision 2 about 48s ago, diff env_added app: [API_VERSION]. orders-api has only revision 1, created 2m ago, and no rollout.
- `kubernetes_pod_logs (inventory-b775d96fd-qq86l)`: "inventory serving /v2/stock". The inventory pod is Running 1/1 with 0 restarts.
- `kubernetes_describe_deployment (inventory)`: Revision 2 is the active ReplicaSet and is Available. Revision 1 (inventory-8469585669) is scaled to 0 replicas. Only the env var changed, not the image.

**Recommendations**
1. Confirm the intended inventory API change with the owning team. The API_VERSION change appears to have moved stock from /stock to /v2/stock, which breaks orders-api 2.3.0.
2. Preferred fast mitigation: roll back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders, or pin the previous ReplicaSet). This needs human approval. Revision 1 was serving /stock and orders-api worked against it.
3. Alternative: if /v2 is the intended contract, point orders-api at the /v2/stock path (INVENTORY_URL or code change) and roll it out. Do not restart orders-api alone, because the crash is caused by the 404 and a restart will not fix it.
4. After the fix, confirm orders-api reaches Ready 1/1 and that the KubePodCrashLooping alert clears. Then add a retry or backoff to the startup stock sync so a dependency blip does not crash-loop the service.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_describe_pod`
3. `kubernetes_pod_logs`
4. `kubernetes_recent_changes`
5. `kubernetes_describe_deployment`
6. `kubernetes_list_pods`
7. `kubernetes_pod_logs`
