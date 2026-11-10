**Passed:** The changed deployment, audit revision 1, is healthy. It has 1/1 replicas ready, 0 restarts and no warning events. orders-api was already in CrashLoopBackOff before the change (pod age 1h, 17 restarts), so it is not this change's doing and doesn't fail the Check. Container logs weren't available, so the log condition is judged from pod state and events only.

**Evidence**
- `kubernetes_recent_changes`: Only change in the window: audit revision 1 created 2m ago. inventory revision 5 rolled out 14m ago, before the audit change.
- `kubernetes_list_pods`: audit-6cfdd68f8c-2xr5p is Running 1/1 with 0 restarts for 2m. inventory is 1/1 with 0 restarts. orders-api is in CrashLoopBackOff with 17 restarts and pod age 1h, so it was failing before the change.
- `kubernetes_list_deployments`: audit is 1/1 ready with 1 updated replica and no problems. inventory is 1/1. orders-api is 0/1 with MinimumReplicasUnavailable.
- `kubernetes_get_events`: No warning events for audit. The orders-api BackOff warning (count 55) is the ongoing crash loop. The inventory readiness-probe warnings were last seen 11m and 14m ago, during its own rollout, and inventory is now ready.

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "audit-6cfdd68f8c-2xr5p"} (error)
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-79cd5d49dc-28wnk", "tail_lines": 20} (error)
6. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
