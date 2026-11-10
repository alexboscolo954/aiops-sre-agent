## orders-api has 0/1 replicas ready and is crash-looping (3 restarts). It exits at startup because its stock sync calls http://inventory.orders:8080/stock and gets a 404. The inventory service, rolled out 48s earlier with API_VERSION added, now serves /v2/stock.

**Root cause** (medium confidence, `bad_rollout`): The inventory rollout (revision 2, about 48s before the check, env API_VERSION added) changed the API path to /v2/stock. orders-api (revision 1, unchanged, env INVENTORY_URL) still requests the unversioned /stock path, gets HTTP 404, and exits with code 1 at startup. The inventory logs confirm 'inventory serving /v2/stock'. This is a version mismatch between the two services, inferred from logs and rollout diffs rather than a direct config diff of the path.
**Severity:** high  ·  **Affected:** orders/Deployment/orders-api, orders/Deployment/inventory

**Evidence**
- `kubernetes_list_deployments`: orders-api ready 0/1, Available=False MinimumReplicasUnavailable; inventory 1/1
- `kubernetes_pod_logs`: orders-api-568b7b8d9f-vzp22: 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'
- `kubernetes_pod_logs`: inventory-b775d96fd-qq86l: 'inventory serving /v2/stock'
- `kubernetes_recent_changes`: inventory revision 2 rollout 48s ago, env_added API_VERSION; orders-api has only revision 1 created 2m ago
- `kubernetes_pod_logs`: orders-api restarts 3, exit code 1, pod describe shows Ready=False ContainersNotReady

**Recommendations**
1. Confirm which API path inventory should serve. Either roll back inventory to revision 1 (kubectl rollout undo deployment/inventory -n orders), or update orders-api to call /v2/stock (or set its INVENTORY_URL to the versioned path) and roll it out.
2. Preferably fix orders-api's configuration or coordinate the version change with the owning team, since rolling back inventory is a change to a service that is currently healthy.
3. After the fix, verify orders-api reaches 1/1 ready and the Check passes.

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22", "previous": true}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-568b7b8d9f-vzp22"}
6. `incidents_search` {"keywords": "orders-api inventory stock sync 404"}
7. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "inventory-b775d96fd-qq86l"}
8. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
9. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "orders-api"}
10. `CheckResult` {"passed": false, "summary": "The Check fails: deployment orders-api in namespace orders has 0/1 replicas ready. The inventory deployment is fully ready (1/1).", "evidence": [{"source": "kubernetes_list_deployments", "finding": "orders-api ready 0/1, problem Available=False reason MinimumReplicasUna
11. `CheckResult` {"passed": false, "summary": "The Check fails: deployment orders-api in namespace orders has 0/1 replicas ready. The inventory deployment is fully ready (1/1).", "evidence": [{"source": "kubernetes_list_deployments", "finding": "orders-api ready 0/1, problem Available=False reason MinimumReplicasUna
