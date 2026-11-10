**Passed:** The check holds. Deployment orders/inventory has 1 of 1 replicas ready, and its only pod (inventory-b775d96fd-qq86l) is Running and Ready with 0 restarts. That pod is only 44s old, so this is a short window. Outside this check, orders/orders-api is unhealthy: 0/1 ready, and its pod has restarted 3 times with exit code 1.

**Evidence**
- `kubernetes_list_deployments`: Deployment inventory in orders: ready 1/1, updated 1, image python:3.12-alpine, no problem conditions
- `kubernetes_list_pods`: Pod inventory-b775d96fd-qq86l: phase Running, ready 1/1, restarts 0, no last termination, age 44s
- `kubernetes_list_pods`: Outside this check: pod orders-api-568b7b8d9f-vzp22 is ready 0/1 with 3 restarts, and its container exited with Error, exit code 1

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
