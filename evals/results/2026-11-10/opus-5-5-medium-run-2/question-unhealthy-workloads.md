All three deployments in `demo` are unhealthy. Each has 0 of 1 replicas ready and reports `MinimumReplicasUnavailable`.

1. **checkout** is in a crash loop (exit code 1, 3 restarts). Its log says `FATAL: required env var DATABASE_URL is not set`. The most recent rollout, revision 2 about 36 seconds before I checked, removed `DATABASE_URL` from the container's environment. Revision 1 had it. **Fix:** add `DATABASE_URL` back to the deployment, or roll back to revision 1.

2. **frontend** is stuck in Pending with `ErrImagePull`. The image `nginx:1.99.99-does-not-exist` doesn't exist on Docker Hub ("not found"). **Fix:** change the image to a valid nginx tag.

3. **reports** is in a crash loop, killed for running out of memory (OOMKilled, exit code 137, 3 restarts). Its memory limit is only 48Mi (request 32Mi), and the app keeps going over it. **Fix:** raise the memory limit, or find out why the app needs more memory than that.

I only read the cluster; I didn't change anything. I didn't search past incidents or check other recent changes.

**Evidence**
- `kubernetes_list_deployments`: checkout, frontend and reports in demo are all ready 0/1 with Available=False, MinimumReplicasUnavailable
- `kubernetes_list_pods`: checkout pod terminated with Error, exit 1, 3 restarts; frontend pod Pending with ErrImagePull because nginx:1.99.99-does-not-exist was not found; reports pod OOMKilled, exit 137, 3 restarts
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps log: 'FATAL: required env var DATABASE_URL is not set'
- `kubernetes_describe_deployment`: checkout revision 2 (36s old) has env []; revision 1 had env [DATABASE_URL]
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f: memory limit 48Mi, request 32Mi; state OOMKilled exit 137; BackOff restarting the failed container

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 50}
4. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
