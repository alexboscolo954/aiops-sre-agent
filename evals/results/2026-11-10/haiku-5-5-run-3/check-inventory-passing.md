**Passed:** The Check covers the inventory deployment in namespace orders. It holds: inventory has 1/1 replicas ready and its only pod has 0 restarts. The orders-api deployment in the same namespace is failing (0/1, 3 restarts), but the Check does not cover it.

**Evidence**
- `kubernetes_list_deployments`: inventory: ready 1/1, updated 1, no problems listed.
- `kubernetes_describe_deployment`: inventory: replicas desired 1, ready 1; Available=True (MinimumReplicasAvailable); Progressing=True (NewReplicaSetAvailable).
- `kubernetes_list_pods`: inventory-b775d96fd-qq86l: Running, 1/1 ready, restarts 0, age 44s.

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders", "label_selector": "app=inventory"}
3. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
4. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
5. `CheckResult` {"passed": true, "summary": "The Check covers the inventory deployment in namespace orders. It holds: inventory has 1/1 replicas ready and its only pod has 0 restarts. The orders-api deployment in the same namespace is failing (0/1, 3 restarts), but the Check does not cover it.", "evidence": [{"sour
