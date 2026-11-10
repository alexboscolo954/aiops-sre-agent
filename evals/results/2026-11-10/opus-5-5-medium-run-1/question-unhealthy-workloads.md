All three deployments in `demo` are unhealthy right now. Each one shows 0/1 ready (MinimumReplicasUnavailable).

1. **checkout** is crash-looping (exit code 1, 3 restarts). The app logs `FATAL: required env var DATABASE_URL is not set`. About 48s ago, revision 2 of the deployment removed the `DATABASE_URL` env var from the `app` container. That rollout caused the crash.
   **Fix:** add `DATABASE_URL` back to the deployment, or roll back to revision 1.

2. **frontend** is stuck in Pending with `ErrImagePull`. Its image `nginx:1.99.99-does-not-exist` doesn't exist on Docker Hub (`not found`).
   **Fix:** point the deployment at an nginx tag that exists.

3. **reports** is crash-looping because the container keeps running out of memory (OOMKilled, exit 137, 3 restarts, BackOff). Its memory limit is only 48Mi (request 32Mi), and the app goes over it.
   **Fix:** raise the memory limit, or cut the app's memory use. It's worth checking how much memory it actually needs first.

I didn't search past incidents, because this was a status question rather than alert triage.

**Evidence**
- `kubernetes_list_deployments`: checkout, frontend and reports are all 0/1 ready with Available=False, MinimumReplicasUnavailable
- `kubernetes_list_pods`: checkout pod: Error exit 1, 3 restarts. frontend pod: Pending, ErrImagePull, nginx:1.99.99-does-not-exist not found. reports pod: OOMKilled exit 137, 3 restarts
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'FATAL: required env var DATABASE_URL is not set'
- `kubernetes_recent_changes`: checkout revision 2 rolled out 48s ago with env_removed: app: [DATABASE_URL]
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f: memory limit 48Mi, request 32Mi; state OOMKilled exit 137; BackOff restarting failed container

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 50}
4. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
5. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
