All three deployments in `demo` are unhealthy. Each one has 0 of 1 replicas ready and reports `MinimumReplicasUnavailable`.

1. **checkout**: the app crashes on startup because `DATABASE_URL` is missing.
   - Pod `checkout-869fc5bcc6-db5ps` exits with code 1 and is in BackOff after 3 restarts.
   - Its log says `FATAL: required env var DATABASE_URL is not set`.
   - The cause is a rollout about 48 seconds before I checked. It created revision 2, and the only change from revision 1 was removing `DATABASE_URL` from the `app` container.
   - **Fix:** add `DATABASE_URL` back, or roll back to revision 1.

2. **frontend**: the image doesn't exist.
   - Pod `frontend-6f6b4986b9-hxdf2` is stuck in Pending with ErrImagePull / ImagePullBackOff.
   - It's trying to pull `nginx:1.99.99-does-not-exist`, and the registry answers `not found`.
   - **Fix:** point the deployment at a real nginx tag.

3. **reports**: the container runs out of memory.
   - Pod `reports-55b4fffc66-hmq7f` keeps getting OOMKilled (exit 137) and is in BackOff after 3 restarts.
   - Its memory limit is only 48Mi, with 32Mi requested.
   - **Fix:** raise the memory limit, or find out why the app needs more than 48Mi. I didn't read this pod's logs, so I haven't confirmed which.

About 2 minutes before I checked, all three pods also had a one-off FailedScheduling event (`untolerated taint`). That cleared up, and all three are now running on `squero-control-plane`, so it isn't the cause of any of these failures.

**Evidence**
- `kubernetes_list_deployments`: checkout, frontend, reports all 0/1 ready with Available=False MinimumReplicasUnavailable; frontend image nginx:1.99.99-does-not-exist
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps Error exit 1 (3 restarts); frontend-6f6b4986b9-hxdf2 Pending ErrImagePull 'nginx:1.99.99-does-not-exist: not found'; reports-55b4fffc66-hmq7f OOMKilled exit 137 (3 restarts)
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'FATAL: required env var DATABASE_URL is not set'
- `kubernetes_recent_changes`: checkout revision 2 rolled out 48s ago with env_removed: app: [DATABASE_URL]
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f container app limits memory 48Mi, requests 32Mi; state OOMKilled exit 137, restarts 3
- `kubernetes_get_events`: BackOff restarting checkout and reports containers; frontend Failed to pull image / ImagePullBackOff; earlier one-off FailedScheduling 'untolerated taint(s)' 2m ago

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "demo"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 50}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
6. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
