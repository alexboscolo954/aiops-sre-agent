**Passed:** Deployment orders/inventory has 1/1 replicas ready. Its only pod, inventory-b775d96fd-qq86l, is Running and Ready with 0 restarts, so the Check holds. The pod is only 44s old, which may point to a recent rollout or replacement, but it has not restarted. orders-api in the same namespace is failing (0/1 ready, 3 restarts, exit code 1), but this Check doesn't cover it.

**Evidence**
- `kubernetes_list_deployments`: inventory in orders: ready 1/1, updated 1, image python:3.12-alpine, no problem conditions
- `kubernetes_list_pods`: inventory-b775d96fd-qq86l: phase Running, ready 1/1, restarts 0, no last termination, age 44s

**Tool calls**
1. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "orders"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "orders"}
