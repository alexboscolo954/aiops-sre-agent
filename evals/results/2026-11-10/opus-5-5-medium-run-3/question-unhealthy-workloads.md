All three deployments in `demo` are down. Each shows **0/1 ready** with `MinimumReplicasUnavailable`, and each fails for a different reason:

1. **checkout** is crash-looping (exit code 1, 3 restarts). The container logs `FATAL: required env var DATABASE_URL is not set`. The cause is a rollout about 48s ago (revision 2) that **removed the `DATABASE_URL` env var** from the `app` container. **Fix:** add `DATABASE_URL` back, or roll back to revision 1.

2. **frontend** never starts. The pod is stuck in Pending with `ErrImagePull` because the image `nginx:1.99.99-does-not-exist` doesn't exist on Docker Hub (`not found`). **Fix:** point the deployment at an nginx tag that exists.

3. **reports** is crash-looping because it runs out of memory: it's been **OOMKilled** (exit code 137, 3 restarts). Its memory limit is only **48Mi** (request 32Mi), and the python app goes over it. Nothing about reports has changed since it was created. **Fix:** raise the memory limit, or cut the app's memory use.

The reports pod also had an earlier one-off `FailedScheduling` event (untolerated node taint). It was then scheduled, so that isn't the current problem.

**Evidence**
- `kubernetes_list_pods`: checkout pod 0/1, Error exit 1, 3 restarts; frontend pod Pending ErrImagePull for nginx:1.99.99-does-not-exist (not found); reports pod OOMKilled exit 137, 3 restarts
- `kubernetes_list_deployments`: checkout, frontend, reports all 0/1 ready with MinimumReplicasUnavailable
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'FATAL: required env var DATABASE_URL is not set'
- `kubernetes_recent_changes`: checkout revision 2 rolled out 48s ago with env_removed: DATABASE_URL; frontend and reports only created (rev 1) 2m ago
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f: memory limit 48Mi, request 32Mi; state OOMKilled exit 137; BackOff restarting failed container

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 50}
4. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
5. `kubernetes_recent_changes` {"cluster": "kind"}
