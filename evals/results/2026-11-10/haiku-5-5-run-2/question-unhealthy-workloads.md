Three workloads in namespace `demo` are unhealthy (all deployments at 0/1 available). Each has a different cause:

1. **checkout** (crash loop, Error exit 1): Revision 2 removed the `DATABASE_URL` env var from the `app` container. The app exits on startup with `FATAL: required env var DATABASE_URL is not set`. This rollout happened about 48s before the check, so it is the likely trigger. Fix: restore `DATABASE_URL` in the checkout deployment (or roll back to revision 1).

2. **reports** (crash loop, OOMKilled, exit 137): The container has a memory limit of 48Mi and is being killed for exceeding it. The pod also took 1m21s to pull `python:3.12-alpine` and earlier logged a FailedScheduling taint event. Fix: raise the memory limit (the 32Mi request and 48Mi limit are very tight for a Python process), and check whether the node taint that blocked scheduling is still relevant.

3. **frontend** (ImagePullBackOff / ErrImagePull): The image `nginx:1.99.99-does-not-exist` does not exist on Docker Hub, so the pod never starts. Fix: point the deployment at a valid tag (for example an existing nginx 1.x release) and roll it out.

No past incidents matched these workloads. No rollout changes were recorded for reports or frontend beyond their initial creation.

**Evidence**
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps: Running, 0/1 ready, 3 restarts, last terminated Error exit 1; reports-55b4fffc66-hmq7f: 0/1 ready, 3 restarts, OOMKilled exit 137; frontend-6f6b4986b9-hxdf2: Pending, 0/1, waiting ErrImagePull for docker.io/library/nginx:1.99.99-does-not-exist (not found).
- `kubernetes_list_deployments`: checkout, frontend and reports all at 0/1 ready with MinimumReplicasUnavailable.
- `kubernetes_pod_logs`: checkout previous logs: 'FATAL: required env var DATABASE_URL is not set' followed by 'checkout starting, version 1.4.0'.
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f: container app, state OOMKilled exit 137, limits memory 48Mi, requests memory 32Mi, env empty; events show FailedScheduling taint warning and image pull of 1m21s.
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago with diff env_removed app: [DATABASE_URL]; checkout revision 1, frontend revision 1 and reports revision 1 only 'created' 2m ago with no diff.

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true}
4. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
5. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 30}
6. `incidents_search` {"keywords": "checkout reports frontend demo", "limit": 5}
7. `Answer` {"answer": "Three workloads in namespace `demo` are unhealthy (all deployments at 0/1 available). Each has a different cause:\n\n1. **checkout** (crash loop, Error exit 1): Revision 2 removed the `DATABASE_URL` env var from the `app` container. The app exits on startup with `FATAL: required env var 
