**Passed:** The new audit deployment (revision 1, created 2m ago) is healthy. It has 1/1 replicas ready on its only revision, its pod hasn't restarted, it has no warning events and nothing else in the namespace started failing after it. orders-api was already crash-looping before the change and still fails the same way (CrashLoopBackOff, exit code 1). That isn't this change's doing, so the Check doesn't fail for it.

**Evidence**
- `kubernetes_recent_changes`: audit revision 1 was created 2m ago (it's a new deployment, so there's no earlier revision to compare). The only other change was the inventory revision 5 rollout 14m ago, which added the env vars API_VERSION and BUILD; that was before the audit change.
- `kubernetes_list_deployments`: audit: 1/1 ready, 1 updated, image registry.k8s.io/pause:3.10, no problems. inventory: 1/1 ready. orders-api: 0/1 ready, MinimumReplicasUnavailable.
- `kubernetes_list_pods`: Pod audit-6cfdd68f8c-2xr5p is Running, 1/1 ready, 0 restarts, age 2m. inventory-b775d96fd-rmlvd is 1/1 ready with 0 restarts. orders-api-79cd5d49dc-28wnk (age 1h) is in CrashLoopBackOff with 17 restarts; its last run ended with Error, exit code 1.
- `kubernetes_describe_pod`: audit pod: Ready and ContainersReady are True and it has only Normal events (Scheduled, Pulled, Created, Started). Its single container runs the pause image, which writes no logs. The log tool returned 'no recorded data' for this pod, so the logs couldn't be read directly.
- `kubernetes_get_events`: No warning events for audit. The warnings in the namespace are an orders-api BackOff (count 55, last seen 4m) and one failed readiness probe each on the inventory pods 11m and 14m ago, during the earlier inventory rollout.
- `kubernetes_describe_pod`: orders-api pod: CrashLoopBackOff, last terminated with Error, exit code 1, restarts 17. Its events go back 44-49m (Created count 10, Started count 9), so it was failing well before audit was created 2m ago. Its only env var is INVENTORY_URL, so it has no tie to audit.

**Tool calls**
1. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
4. `kubernetes_get_events` {"cluster": "kind", "namespace": "orders"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "audit-6cfdd68f8c-2xr5p", "tail_lines": 50} (error)
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "orders", "name": "orders-api-79cd5d49dc-28wnk", "tail_lines": 50} (error)
7. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "audit-6cfdd68f8c-2xr5p"}
8. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "orders", "name": "orders-api-79cd5d49dc-28wnk"}
