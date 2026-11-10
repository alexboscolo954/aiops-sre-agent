**Passed:** Deployment orders/inventory has 1/1 replicas ready, and its pod inventory-b775d96fd-qq86l is Running with 0 restarts. orders-api in the same namespace is failing, but this Check doesn't cover it.

**Evidence**
- `kubernetes_list_deployments`: inventory ready 1/1, updated 1, no problems listed
- `kubernetes_list_pods`: inventory-b775d96fd-qq86l: phase Running, ready 1/1, restarts 0, no previous terminations (pod is 44s old)
- `kubernetes_list_pods`: Outside this Check: orders-api-568b7b8d9f-vzp22 is ready 0/1 with 3 restarts, exit code 1 (Error)

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
