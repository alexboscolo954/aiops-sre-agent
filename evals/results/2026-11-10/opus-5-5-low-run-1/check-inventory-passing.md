**Passed:** The Check passes. The inventory deployment in orders has 1 of 1 replicas ready, and its only pod, inventory-b775d96fd-qq86l, is Running and ready with 0 restarts. Outside this Check's scope, orders-api has 0 of 1 replicas ready and its pod has restarted 3 times.

**Evidence**
- `kubernetes_list_deployments`: Deployment inventory shows ready 1/1, updated 1, with no problems listed.
- `kubernetes_list_pods`: Pod inventory-b775d96fd-qq86l is Running, ready 1/1, restarts 0, age 44s. Separately, orders-api-568b7b8d9f-vzp22 is 0/1 ready with 3 restarts and exited with code 1.

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
