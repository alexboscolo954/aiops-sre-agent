**Passed:** The audit deployment (the change under test, revision 1) is healthy: 1/1 ready on its new ReplicaSet, 0 restarts, running for 2m, and no warning events for it. orders-api was already failing before this change: it is CrashLoopBackOff with 17 restarts over a 1h pod age, and its log shows a stock sync 404 from inventory.orders. The audit change did not touch it, so it is noted here, not failed against this Check. The inventory rollout (revision 5, 14m ago) predates the audit change and inventory is 1/1 ready now.

**Evidence**
- `kubernetes_recent_changes`: audit rollout: revision 1, change 'created', 2m ago; inventory rollout: revision 5 at 14m ago, env_added API_VERSION and BUILD.
- `kubernetes_list_deployments`: audit ready 1/1, updated 1, no problems; inventory ready 1/1; orders-api ready 0/1 with MinimumReplicasUnavailable.
- `kubernetes_describe_pod`: audit-6cfdd68f8c-2xr5p: Ready=True, ContainersReady=True, restarts 0, pause container running since 2m; events are only Normal (Scheduled, Pulled, Created, Started).
- `kubernetes_list_pods`: audit-6cfdd68f8c-2xr5p Running 1/1, restarts 0, age 2m; orders-api-79cd5d49dc-28wnk 0/1, restarts 17, CrashLoopBackOff, age 1h.
- `kubernetes_get_events`: Warnings in orders are only for orders-api BackOff (count 55, last seen 4m) and inventory readiness probe 'connection refused' events at 11m and 14m, none for audit.
- `kubernetes_pod_logs`: orders-api previous run: 'orders-api starting, version 2.3.0' then 'FATAL: stock sync failed: GET http://inventory.orders:8080/stock: HTTP Error 404: Not Found'.

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 30}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders", "label_selector": ""}
4. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders", "warnings_only": true}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "audit-6cfdd68f8c-2xr5p"}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-79cd5d49dc-28wnk", "container": "app", "tail_lines": 30, "previous": true}
7. `incidents_search` {"keywords": "orders-api audit", "days": 90, "limit": 5}
