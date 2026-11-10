**Passed:** The Check holds for the inventory deployment: it has 1/1 replicas ready and its only pod has 0 restarts. Note that the other deployment in namespace orders, orders-api, is not ready (0/1) and its pod is crash-looping with 3 restarts; the Check does not cover it, but it is flagged below.

**Evidence**
- `kubernetes_list_deployments`: inventory: ready 1/1, updated 1, no problems. orders-api: ready 0/1, problem Available=False reason MinimumReplicasUnavailable.
- `kubernetes_describe_deployment`: inventory: replicas desired 1, ready 1; Available=True MinimumReplicasAvailable; Progressing=True NewReplicaSetAvailable.
- `kubernetes_list_pods`: inventory-b775d96fd-qq86l: Running, ready 1/1, restarts 0, age 44s.
- `kubernetes_list_pods`: orders-api-568b7b8d9f-vzp22 (outside the Check's scope): ready 0/1, restarts 3, last termination Error exit code 1.

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders", "label_selector": "app=inventory"}
3. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "orders", "name": "inventory"}
4. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
5. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
6. `CheckResult` {"passed": true, "summary": "The Check holds for the inventory deployment: it has 1/1 replicas ready and its only pod has 0 restarts. Note that the other deployment in namespace orders, orders-api, is not ready (0/1) and its pod is crash-looping with 3 restarts; the Check does not cover it, but it i
