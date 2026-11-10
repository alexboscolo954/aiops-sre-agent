**Passed:** The 'inventory' deployment in namespace orders has all its replicas ready (1/1) and its only pod has zero restarts, so the Check holds. Note that the sibling deployment orders-api is failing (0/1, 3 restarts), but it is outside the Check's scope.

**Evidence**
- `kubernetes_list_deployments`: inventory: ready 1/1, updated 1, no problems listed.
- `kubernetes_list_pods`: inventory-b775d96fd-qq86l: Running, ready 1/1, restarts 0, age 44s (label app=inventory).
- `kubernetes_describe_deployment`: inventory: desired 1, ready 1; Available=True (MinimumReplicasAvailable); Progressing=True (NewReplicaSetAvailable).

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders", "label_selector": "app=inventory"}
3. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
4. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
5. `CheckResult` {"passed": true, "summary": "The 'inventory' deployment in namespace orders has all its replicas ready (1/1) and its only pod has zero restarts, so the Check holds. Note that the sibling deployment orders-api is failing (0/1, 3 restarts), but it is outside the Check's scope.", "evidence": [{"source"
