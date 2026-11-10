**Passed:** The inventory deployment in namespace orders has 1/1 replicas ready and its only pod, inventory-b775d96fd-qq86l, shows 0 restarts. The separate orders-api deployment is failing (0/1 ready, 3 restarts), but it is outside this Check's scope.

**Evidence**
- `kubernetes_list_deployments`: inventory: ready 1/1, updated 1, no problems listed.
- `kubernetes_list_pods`: inventory-b775d96fd-qq86l: phase Running, ready 1/1, restarts 0, running for 44s, no last_terminated state.
- `kubernetes_list_pods`: Out of scope but noted: orders-api-568b7b8d9f-vzp22 is 0/1 ready with 3 restarts (last exit code 1), and the orders-api deployment reports MinimumReplicasUnavailable.

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders", "label_selector": ""}
