## orders-api is crash looping because its startup stock sync gets HTTP 404 from inventory.orders:8080/stock. The inventory deployment rolled out revision 2 (new env var API_VERSION) shortly before.

**Root cause** (medium confidence, `bad_rollout`): orders-api exits with code 1 at startup: "FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found". The only other change in the namespace is inventory revision 2 (about 48s ago), which added the env var API_VERSION. That points to the rollout changing the API that inventory serves, so /stock is no longer found. The 404 is confirmed. The link to the rollout is inferred from timing and the env diff. I did not see inventory's logs or routes, and orders-api's first crash may have come before the rollout (revision 1 was created at the same time as orders-api).
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22 logs: 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'. These are the latest instance's logs, because the previous instance's logs were gone.
- `kubernetes_list_pods`: orders-api pod is 0/1 ready with 3 restarts, last terminated Error with exit code 1. The inventory pod is Running 1/1 and is 44s old.
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago and added env var API_VERSION. orders-api has had no rollout since it was created (revision 1).
- `kubernetes_describe_deployment`: inventory revision 2 (ReplicaSet inventory-b775d96fd) uses the same image python:3.12-alpine as revision 1. The only difference is the new API_VERSION env var, so the behaviour change comes from config.

**Recommendations**
1. Check inventory's logs and routes to confirm whether /stock is missing or has moved under the new API_VERSION setting.
2. Roll back inventory to revision 1 (or fix or remove API_VERSION) and check that GET /stock returns 200.
3. After inventory is fixed, watch orders-api recover on its own. Don't restart it, because a restart won't fix a crash loop.
4. Longer term, make orders-api retry the stock sync with backoff instead of exiting at startup, and check inventory API compatibility before rollouts.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 40}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
