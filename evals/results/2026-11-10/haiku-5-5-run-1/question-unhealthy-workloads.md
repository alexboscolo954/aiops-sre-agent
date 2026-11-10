Three workloads in namespace `demo` are unhealthy. All three deployments have 0/1 ready replicas.

1. **checkout** (`checkout-869fc5bcc6-db5ps`): crash-looping with exit code 1. The app exits at startup with `FATAL: required env var DATABASE_URL is not set`. The fix is to supply `DATABASE_URL` to the deployment (for example via a Secret or ConfigMap), since the container has no env configured to supply it.

2. **frontend** (`frontend-6f6b4986b9-hxdf2`): stuck Pending with `ErrImagePull`. The image `nginx:1.99.99-does-not-exist` does not exist on docker.io. The fix is to point the deployment at a valid tag, such as an existing nginx release.

3. **reports** (`reports-55b4fffc66-hmq7f`): OOMKilled (exit 137) and restarting. The container has a 48Mi memory limit, and its logs show it loading about 200MB of rows to build the monthly report before it is killed. The fix is to raise the memory limit substantially or to change the job to process the data in smaller batches.

I did not check recent rollouts (`kubernetes_recent_changes`) or past incidents, so I can't say whether any of these were caused by a recent change.

**Evidence**
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps 0/1, 3 restarts, last terminated Error exit 1; frontend-6f6b4986b9-hxdf2 Pending, waiting ErrImagePull; reports-55b4fffc66-hmq7f 0/1, 3 restarts, OOMKilled exit 137.
- `kubernetes_list_deployments`: checkout, frontend and reports all 0/1 ready with MinimumReplicasUnavailable. frontend image is nginx:1.99.99-does-not-exist; checkout and reports use python:3.12-alpine.
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps logs: 'FATAL: required env var DATABASE_URL is not set' followed by 'checkout starting, version 1.4.0'.
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f: container app state OOMKilled exit 137, 3 restarts, memory limit 48Mi, request 32Mi, env list empty.
- `kubernetes_pod_logs`: reports-55b4fffc66-hmq7f previous log: 'building monthly report: loading 200MB of rows'.
- `kubernetes_describe_pod`: frontend and checkout pods were not described; the ErrImagePull message ('failed to resolve reference docker.io/library/nginx:1.99.99-does-not-exist: not found') came from kubernetes_list_pods.

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true}
4. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true}
7. `Answer` {"answer": "Three workloads in namespace `demo` are unhealthy. All three deployments have 0/1 ready replicas.\n\n1. **checkout** (`checkout-869fc5bcc6-db5ps`): crash-looping with exit code 1. The app exits at startup with `FATAL: required env var DATABASE_URL is not set`. The fix is to supply `DATAB
