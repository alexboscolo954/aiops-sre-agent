**Passed:** The check passed. The inventory deployment in orders has 1 of 1 replicas ready, and its only pod (inventory-b775d96fd-qq86l) is Running, 1/1 ready, with 0 restarts. Outside this check, orders-api in the same namespace is failing: 0 of 1 replicas ready and 3 restarts with exit code 1.

**Evidence**
- `kubernetes_list_deployments`: inventory ready 1/1, updated 1, no problems; orders-api ready 0/1 (MinimumReplicasUnavailable), which this check doesn't cover
- `kubernetes_list_pods`: inventory-b775d96fd-qq86l Running, ready 1/1, restarts 0, age 44s

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
