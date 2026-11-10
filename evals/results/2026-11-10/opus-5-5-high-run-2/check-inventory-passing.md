**Passed:** The Check holds: Deployment orders/inventory has 1 of 1 replicas ready, and its only pod (inventory-b775d96fd-qq86l) is Running and ready with 0 restarts. That pod is only 44s old, so this covers only its short life. Separately, orders-api in the same namespace is failing (0/1 ready, 3 restarts, exit code 1), but this Check doesn't cover it.

**Evidence**
- `kubernetes_list_deployments`: Deployment inventory in orders: ready 1/1, updated 1, no failing conditions.
- `kubernetes_list_pods`: Pod inventory-b775d96fd-qq86l: phase Running, ready 1/1, restarts 0, no last termination, age 44s.
- `kubernetes_list_pods`: Outside this Check: pod orders-api-568b7b8d9f-vzp22 is 0/1 ready with 3 restarts and terminated with Error (exit code 1).

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
