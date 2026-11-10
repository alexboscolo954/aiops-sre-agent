**Passed:** Deployment inventory in orders has 1/1 replicas ready, and its pod has 0 restarts. The pod is only 44s old because revision 2 rolled out about 48s ago. orders-api in the same namespace is crash-looping, but the Check does not cover it.

**Evidence**
- `kubernetes_list_deployments`: inventory ready 1/1, updated 1, no problems. (orders-api is 0/1 and unavailable, which is out of scope.)
- `kubernetes_list_pods`: inventory-b775d96fd-qq86l is Running, ready 1/1, restarts 0, container app running for 44s.
- `kubernetes_recent_changes`: inventory revision 2 rolled out 48s ago and added the env var API_VERSION. The old pod was replaced, and the new pod has not restarted.

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
