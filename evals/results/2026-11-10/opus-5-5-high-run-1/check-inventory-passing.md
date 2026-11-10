**Passed:** The check passes. Deployment orders/inventory has 1/1 replicas ready, and its only pod, inventory-b775d96fd-qq86l, is Running and ready with 0 restarts. That pod is only 44s old, so a 0 restart count covers a short time. Outside this check: orders-api in the same namespace is not ready (0/1). Its pod has restarted 3 times and its container exited with code 1.

**Evidence**
- `kubernetes_list_deployments`: Deployment inventory in orders: ready 1/1, updated 1, image python:3.12-alpine, no problems reported.
- `kubernetes_list_pods`: Pod inventory-b775d96fd-qq86l: phase Running, ready 1/1, restarts 0, no last termination, age 44s.
- `kubernetes_list_pods`: Outside the check: pod orders-api-568b7b8d9f-vzp22 is ready 0/1 with 3 restarts, and its last termination was Error with exit code 1. kubernetes_list_deployments also shows orders-api at 0/1 with MinimumReplicasUnavailable.

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
