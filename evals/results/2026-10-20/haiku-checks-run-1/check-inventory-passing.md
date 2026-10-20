**Passed:** The inventory deployment in namespace orders is fully ready (1/1 replicas, updated 1) and its pod inventory-b775d96fd-qq86l has 0 restarts, so the Check holds. Out of scope for this Check, orders-api in the same namespace is 0/1 ready with 3 restarts and is failing.

**Evidence**
- `kubernetes_list_deployments`: inventory: ready "1/1", updated 1, no problems listed (namespace orders).
- `kubernetes_list_pods`: inventory-b775d96fd-qq86l: phase Running, ready 1/1, restarts 0, last_terminated empty, age 44s.
- `kubernetes_list_pods`: Not part of this Check: orders-api-568b7b8d9f-vzp22 is 0/1 ready with restarts 3 (last termination Error, exit code 1), and its deployment reports MinimumReplicasUnavailable.

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders", "label_selector": ""}
