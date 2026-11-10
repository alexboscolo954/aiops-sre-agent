All three deployments in `demo` are unhealthy. Each has 0 of 1 replicas ready.

1. **checkout**: the container keeps crashing (exit code 1, 3 restarts). Its log shows `FATAL: required env var DATABASE_URL is not set`. **Fix:** set `DATABASE_URL` in the deployment, either directly or from a Secret or ConfigMap.
2. **frontend**: the pod is stuck in Pending with `ErrImagePull`. Its image `nginx:1.99.99-does-not-exist` doesn't exist on Docker Hub. **Fix:** change the image to a real nginx tag, or roll back to the previous version.
3. **reports**: the container is being OOMKilled over and over (exit code 137, 3 restarts, BackOff). Its memory limit is only 48Mi (request 32Mi). **Fix:** raise the memory limit, or find out why the app needs more memory than that.

I didn't check the rollout history, so I can't say which change caused each problem.

**Evidence**
- `kubernetes_list_deployments`: checkout, frontend, reports all 0/1 ready, MinimumReplicasUnavailable
- `kubernetes_list_pods`: checkout pod Error exit 1 (3 restarts); frontend pod ErrImagePull for nginx:1.99.99-does-not-exist: not found; reports pod OOMKilled exit 137 (3 restarts)
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'FATAL: required env var DATABASE_URL is not set'
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f: memory limit 48Mi, request 32Mi, state OOMKilled, BackOff restarting

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 30}
4. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
