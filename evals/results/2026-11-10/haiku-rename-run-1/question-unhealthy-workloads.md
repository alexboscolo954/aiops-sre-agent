Three workloads in namespace demo are unhealthy, all at 0/1 available. Each has a different cause:

1. **checkout** (python:3.12-alpine): crash loop. Revision 2, rolled out about 48s before the check, removed the `DATABASE_URL` env var from container `app`. The app exits at startup with `FATAL: required env var DATABASE_URL is not set`, so the fix is to restore `DATABASE_URL` on the checkout deployment.

2. **reports** (python:3.12-alpine): crash loop from OOMKill. The container is terminated with OOMKilled (exit 137) and is building a monthly report by "loading 200MB of rows". The memory limit was not inspected. Raising the memory limit or reducing how many rows are loaded at once would address it.

3. **frontend** (nginx:1.99.99-does-not-exist): ImagePullBackOff. The image tag does not exist on docker.io, so the pod never starts. Pointing the deployment at a valid nginx tag would fix it.

No recent rollout explains the reports or frontend failures; both were created about 2 minutes ago. Earlier FailedScheduling events for checkout-67d9799c78 and the first reports and frontend pods were caused by an untolerated node taint, and those events are stale because the current pods are scheduled on squero-control-plane.

**Evidence**
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps 0/1, restarts 3, last terminated Error exit 1; frontend-6f6b4986b9-hxdf2 0/1 Pending, waiting ErrImagePull; reports-55b4fffc66-hmq7f 0/1, restarts 3, terminated OOMKilled exit 137.
- `kubernetes_list_deployments`: checkout, frontend and reports all report 0/1 ready with MinimumReplicasUnavailable; frontend image is nginx:1.99.99-does-not-exist.
- `kubernetes_get_events`: BackOff restarting failed container app for checkout and reports pods; frontend Failed events: 'Failed to pull image "nginx:1.99.99-does-not-exist"... not found' and ErrImagePull/ImagePullBackOff.
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps app container: 'FATAL: required env var DATABASE_URL is not set' followed by 'checkout starting, version 1.4.0'.
- `kubernetes_pod_logs`: reports-55b4fffc66-hmq7f app container: 'building monthly report: loading 200MB of rows'.
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago with diff env_removed app: [DATABASE_URL]; checkout, frontend and reports revision 1 created about 2m ago with no diff.

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": ""}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "demo", "warnings_only": true}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "container": "app", "tail_lines": 50, "previous": false}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "container": "app", "tail_lines": 50, "previous": false}
6. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
