**Passed:** The Check holds: Deployment orders/inventory has 1/1 replicas ready, and its only pod, inventory-b775d96fd-qq86l, is Running with 0 restarts. That pod is only 44s old. Separately, orders-api in the same namespace is not ready (0/1, 3 restarts, exit code 1). This Check doesn't cover it.

**Evidence**
- `kubernetes_list_deployments`: inventory in orders: ready 1/1, updated 1, image python:3.12-alpine, no problems listed
- `kubernetes_list_pods`: inventory-b775d96fd-qq86l: phase Running, ready 1/1, restarts 0, no last termination, age 44s
- `kubernetes_list_pods`: Outside this Check: orders-api-568b7b8d9f-vzp22 is ready 0/1 with 3 restarts, last terminated with Error, exit code 1

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
