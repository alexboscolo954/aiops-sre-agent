## orders-api-568b7b8d9f-vzp22 is crash looping (exit 1, 3 restarts). On startup it calls GET http://inventory.orders:8080/stock and gets HTTP 404. About 48s ago inventory revision 2 added the API_VERSION env var, and inventory now logs 'inventory serving /v2/stock', so it no longer serves the path orders-api calls.

**Root cause** (high confidence, `bad_rollout`): inventory revision 2 (ReplicaSet inventory-b775d96fd, created about 44s ago) added the env var API_VERSION. Revision 1 had no env vars. The new pod logs 'inventory serving /v2/stock'. orders-api 2.3.0 (env INVENTORY_URL) runs a stock sync at startup against /stock and exits when it fails: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'. A dependency rollout changed the API path, so the sync fails and orders-api crash loops. I could only read the latest run's logs because the previous run's logs were gone. I'm assuming inventory.orders is the inventory service; I didn't check that directly. I also didn't verify that /stock worked under revision 1. orders-api's image pull finished about 48s ago, about when inventory revision 2 rolled out, so orders-api may never have run against revision 1.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 Running 0/1, 3 restarts, last terminated Error exit_code 1; inventory-b775d96fd-qq86l is 1/1 and only 44s old
- `kubernetes_pod_logs`: orders-api logs (latest instance; previous ones gone): 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'. inventory-b775d96fd-qq86l logs: 'inventory serving /v2/stock'
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago, diff env_added app: [API_VERSION]; orders-api has only revision 1 (created 2m ago)
- `kubernetes_describe_deployment`: inventory revision 2 (inventory-b775d96fd) has env [API_VERSION]; revision 1 (inventory-8469585669) had none and is scaled to 0
- `kubernetes_describe_pod`: orders-api app container (python:3.12-alpine, env INVENTORY_URL) has BackOff warning 'Back-off restarting failed container app', count 3

**Recommendations**
1. Roll back inventory to revision 1 (kubectl -n orders rollout undo deployment/inventory --to-revision=1) to bring back the /stock path, then check that orders-api passes its startup stock sync and becomes Ready. Needs approval.
2. If inventory is meant to move to /v2/stock, coordinate the change: update orders-api's INVENTORY_URL or client path to the v2 endpoint, or have inventory serve both /stock and /v2/stock during the migration.
3. Don't restart orders-api: a restart won't fix the crash loop while inventory returns 404 on /stock.
4. Consider having orders-api retry or degrade when the stock sync fails at startup, instead of exiting fatally, so one dependency's API change can't crash-loop it.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true}
6. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
7. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l"}
8. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
