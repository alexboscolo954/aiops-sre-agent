## orders-api pod is crash looping because its startup stock sync calls inventory.orders:8080/stock and gets HTTP 404. The inventory deployment was rolled out 48s before the alert (revision 2, which added API_VERSION env), and the orders-api crash is the failing dependency. The root cause is not fully proven; the exact link between the inventory change and the 404 is inferred from timing and the error message.

**Root cause** (medium confidence, `dependency_failure`): orders-api (v2.3.0, python:3.12-alpine) exits at startup with "FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found". It has no retry. The inventory deployment was rolled to revision 2 about 48s before the alert, adding only an API_VERSION env var, and it reports available. The 404 suggests the inventory service no longer serves /stock, or that the path or routing changed. Inventory's logs were not retrievable, and no inventory image or path change appears in the rollout diff, so the link is inferred, not confirmed. The orders-api env (INVENTORY_URL) is set, so this is not a missing-config problem.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Pod/orders-api-568b7b8d9f-vzp22, orders/Deployment/inventory

**Evidence**
- `kubernetes_pod_logs`: orders-api previous/latest instance: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_describe_pod`: container app state Error exit code 1, restarts 3, limits 32Mi memory (no OOMKilled), Ready False ContainersNotReady
- `kubernetes_recent_changes`: inventory revision 2 rollout 48s ago, env_added API_VERSION; orders-api revision 1 created 2m ago, no later change
- `kubernetes_describe_deployment`: inventory revision 2 (inventory-b775d96fd) is the active ReplicaSet, 1/1 ready, Available True; orders-api env INVENTORY_URL set
- `kubernetes_list_deployments`: orders-api ready 0/1, Available False MinimumReplicasUnavailable; inventory ready 1/1

**Recommendations**
1. Check the inventory service's live routes: curl http://inventory.orders:8080/stock from inside the cluster, and confirm the Service endpoints and selector still match the pods.
2. Pull inventory pod logs (the tool returned none for the current ReplicaSet) to see whether /stock is served and what changed in revision 2 (API_VERSION).
3. If inventory revision 2 removed or moved /stock, roll inventory back to revision 1 (kubectl rollout undo deployment/inventory -n orders). This needs approval and is the fix if the rollout caused it.
4. Separately, ask the orders-api team to make the startup stock sync retry with backoff instead of exiting, so a brief dependency outage does not crash-loop the pod.
5. Confirm orders-api recovers (0/1 to 1/1) after the inventory fix; do not restart orders-api alone, since that will not fix the crash loop.

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true}
5. `incidents_search` {"keywords": "orders-api crashloop INVENTORY_URL"}
6. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
7. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
8. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory", "tail_lines": 50} (error)
9. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "orders-api"}
10. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd", "tail_lines": 50} (error)
11. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
12. `TriageReport` {"summary": "orders-api pod is crash looping because its startup stock sync calls inventory.orders:8080/stock and gets HTTP 404. The inventory deployment was rolled out 48s before the alert (revision 2, which added API_VERSION env), and the orders-api crash is the failing dependency. The root cause 
