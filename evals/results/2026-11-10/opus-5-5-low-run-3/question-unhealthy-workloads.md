All three deployments in `demo` are unhealthy. Each has 0 of 1 replicas ready.

1. **checkout**: the pod is crash-looping. It has restarted 3 times and exits with code 1. Its log shows `FATAL: required env var DATABASE_URL is not set`. **Fix:** set `DATABASE_URL` on the deployment, either directly or from a Secret or ConfigMap.
2. **frontend**: the pod is stuck in Pending with `ErrImagePull`. The image `nginx:1.99.99-does-not-exist` doesn't exist on Docker Hub (the pull returns "not found"). **Fix:** change the deployment to a real nginx tag.
3. **reports**: the pod keeps getting OOMKilled (exit code 137, 3 restarts, now in BackOff). Its memory limit is only 48Mi, with a 32Mi request. **Fix:** raise the memory limit, or reduce how much memory the app uses.

I didn't check recent rollouts or past incidents. That would tell you which change introduced these problems.

**Evidence**
- `kubernetes_list_pods`: checkout restarts=3 Error exit 1; frontend Pending ErrImagePull nginx:1.99.99-does-not-exist not found; reports OOMKilled exit 137 restarts=3
- `kubernetes_list_deployments`: checkout, frontend, reports all 0/1 ready, MinimumReplicasUnavailable
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'FATAL: required env var DATABASE_URL is not set'
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f: memory limit 48Mi, request 32Mi, state OOMKilled, BackOff events

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 30}
4. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
