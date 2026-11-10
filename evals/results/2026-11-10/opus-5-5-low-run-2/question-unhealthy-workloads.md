All three deployments in `demo` are unhealthy. Each one has 0 of 1 replicas ready.

1. **checkout**: the app crashes on startup and keeps restarting (3 restarts so far, exit code 1). Its log says `FATAL: required env var DATABASE_URL is not set`. **Fix:** set `DATABASE_URL` on the deployment, either directly or from a Secret or ConfigMap.
2. **frontend**: the pod is stuck in Pending with `ErrImagePull`. The image `nginx:1.99.99-does-not-exist` doesn't exist on Docker Hub. **Fix:** change the image to a tag that exists, or roll back to the previous revision.
3. **reports**: the container keeps running out of memory and getting killed (`OOMKilled`, exit code 137, 3 restarts, now in BackOff). Its memory limit is only 48Mi, with a 32Mi request. **Fix:** raise the memory limit, or reduce how much memory the app uses.

I didn't check rollout history, so I can't say what changed to cause these problems.

**Evidence**
- `kubernetes_list_deployments`: checkout, frontend and reports each show 0/1 ready with MinimumReplicasUnavailable; frontend's image is nginx:1.99.99-does-not-exist
- `kubernetes_list_pods`: checkout pod: Error exit 1 with 3 restarts; frontend pod: Pending with ErrImagePull because the nginx:1.99.99-does-not-exist tag was not found; reports pod: OOMKilled exit 137 with 3 restarts
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps log: 'FATAL: required env var DATABASE_URL is not set'
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f: memory limit 48Mi, request 32Mi; OOMKilled; BackOff restarting the failed container

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 30}
4. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
