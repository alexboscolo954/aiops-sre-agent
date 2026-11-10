All three deployments in `demo` are down. Each one has 0 of 1 replicas ready and the condition `MinimumReplicasUnavailable`.

1. **checkout** is in CrashLoopBackOff (3 restarts, exit code 1) because `DATABASE_URL` is missing. The container logs `FATAL: required env var DATABASE_URL is not set` and exits. About 48 seconds before I checked, a rollout (revision 2) removed `DATABASE_URL` from the `app` container. Revision 1 still had it. **Fix:** add `DATABASE_URL` back to the deployment, or roll checkout back to revision 1.

2. **frontend** can't start because its image doesn't exist. Pod `frontend-6f6b4986b9-hxdf2` is stuck in ErrImagePull / ImagePullBackOff. The deployment uses `nginx:1.99.99-does-not-exist`, and the registry answers `NotFound`. This tag has been there since frontend was created (revision 1). **Fix:** change the image to a real nginx tag.

3. **reports** keeps running out of memory. Pod `reports-55b4fffc66-hmq7f` is restart-looping: it's been OOMKilled (exit code 137) 3 times. Its memory limit is only `48Mi` (request `32Mi`), and the process uses more than that. This has happened since reports was created, not after a change. **Fix:** raise the memory limit, or reduce the app's memory use.

All three pods also had a single `FailedScheduling` event (untolerated node taint) about 2 minutes earlier. That has cleared: they are all now on `squero-control-plane`, so it isn't what's causing the failures now.

**Evidence**
- `kubernetes_list_deployments`: checkout, frontend, reports all 0/1 ready with Available=False MinimumReplicasUnavailable; frontend image nginx:1.99.99-does-not-exist
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps Error exit 1 (3 restarts); frontend-6f6b4986b9-hxdf2 ErrImagePull (not found); reports-55b4fffc66-hmq7f OOMKilled exit 137 (3 restarts)
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'FATAL: required env var DATABASE_URL is not set'
- `kubernetes_recent_changes`: 48s ago checkout revision 2 rollout: env_removed app: [DATABASE_URL]; frontend and reports only created (revision 1) 2m ago
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f: memory limit 48Mi, request 32Mi, state OOMKilled exit 137, restarts 3
- `kubernetes_get_events`: BackOff on checkout and reports pods; frontend 'Failed to pull image nginx:1.99.99-does-not-exist ... not found'; earlier one-off FailedScheduling (untolerated taint) 2m ago

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "demo"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 50}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
6. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
