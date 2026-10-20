Three workloads in namespace demo are unhealthy, each at 0/1 ready with MinimumReplicasUnavailable:

1. **checkout** (pod checkout-869fc5bcc6-db5ps): crash-looping with exit code 1, 3 restarts. The app log says `FATAL: required env var DATABASE_URL is not set`. The pod spec has no DATABASE_URL, so the fix is to add that env var, for example from a Secret or ConfigMap, and roll the deployment.

2. **frontend** (pod frontend-6f6b4986b9-hxdf2): stuck in Pending with ErrImagePull/ImagePullBackOff. The image `nginx:1.99.99-does-not-exist` does not exist on Docker Hub. The fix is to point the deployment at a valid nginx tag.

3. **reports** (pod reports-55b4fffc66-hmq7f): crash-looping with OOMKilled (exit 137), 3 restarts. The container has a memory limit of only 48Mi (request 32Mi). The fix is to raise the memory limit, after confirming the workload's real footprint.

All three pods are on the single node aiops-control-plane. The old checkout ReplicaSet pod (checkout-67d9799c78-n6mfv) and the earlier reports and frontend pods show FailedScheduling events from an untolerated taint. Those are stale events from before the current pods were created, and they are not the current problem.

**Evidence**
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps Running 0/1, restarts 3, last terminated Error exit 1; frontend-6f6b4986b9-hxdf2 Pending 0/1, waiting ErrImagePull; reports-55b4fffc66-hmq7f Running 0/1, restarts 3, terminated OOMKilled exit 137
- `kubernetes_list_deployments`: checkout, frontend and reports each 0/1 ready, Available condition MinimumReplicasUnavailable; frontend image nginx:1.99.99-does-not-exist, checkout and reports image python:3.12-alpine
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps app log: 'FATAL: required env var DATABASE_URL is not set' then 'checkout starting, version 1.4.0'
- `kubernetes_get_events`: frontend: 'Failed to pull image "nginx:1.99.99-does-not-exist": ... not found' with Error: ImagePullBackOff; checkout and reports: BackOff restarting failed container app; reports and checkout FailedScheduling untolerated taint events on older pods
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f container app: state terminated OOMKilled exit 137, restarts 3, memory request 32Mi, limit 48Mi, no env vars defined

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": ""}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "demo", "warnings_only": true}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "container": "app", "tail_lines": 50, "previous": false}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
