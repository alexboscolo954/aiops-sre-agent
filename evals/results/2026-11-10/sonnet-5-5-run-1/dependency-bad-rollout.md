## orders-api is crash looping because its startup stock sync gets HTTP 404 from inventory.orders:8080/stock. The inventory deployment rolled out revision 2 about 48s ago and added an API_VERSION env var.

**Root cause** (medium confidence, `bad_rollout`): orders-api exits with code 1 at startup: "FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found". The only recent change is inventory revision 2, which added env var API_VERSION to the app container. Revision 1 had no env vars. The likely cause is that this setting changed the API path or version inventory serves, so /stock now returns 404. I did not see the inventory code or its logs, so how API_VERSION changes the route is inferred. orders-api has no retry or tolerance for a failed dependency at startup.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 is 0/1 ready with 3 restarts. The last termination was Error, exit code 1. inventory-b775d96fd-qq86l is Running 1/1.
- `kubernetes_pod_logs`: orders-api 2.3.0 logs: FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found. The previous instance's logs were gone, so these are from the latest instance.
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago and added env var API_VERSION. orders-api has only its original revision 1 and was not changed.
- `kubernetes_describe_deployment`: inventory revision 2 (ReplicaSet inventory-b775d96fd) has env [API_VERSION]. Revision 1 (ReplicaSet inventory-8469585669) had no env. The image is the same (python:3.12-alpine), so the env var is the only difference.

**Recommendations**
1. Roll back deployment orders/inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders) and confirm orders-api recovers on its next restart.
2. Check the inventory pod's logs and what API_VERSION does to its routes. Find out why /stock returns 404 and fix the value, or update orders-api to the new path.
3. Make orders-api retry the stock sync with backoff instead of exiting at startup, so a dependency hiccup does not cause a crash loop.
4. Don't restart orders-api as a fix. It will keep crashing until inventory serves /stock again.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "orders-api"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true, "tail_lines": 30}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
