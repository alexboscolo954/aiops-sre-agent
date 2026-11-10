All three Deployments in `demo` are down, each showing **0/1 ready** with `MinimumReplicasUnavailable`. Each one fails for a different reason.

| Workload | Symptom | Cause |
|---|---|---|
| **checkout** | CrashLoopBackOff: exit code 1, 3 restarts | Revision 2, rolled out about 48s ago, **removed the `DATABASE_URL` env var**. The app logs `FATAL: required env var DATABASE_URL is not set` and exits on startup. |
| **frontend** | Pending, stuck in ErrImagePull/ImagePullBackOff | The image `nginx:1.99.99-does-not-exist` doesn't exist on Docker Hub (`not found`). |
| **reports** | CrashLoopBackOff: OOMKilled, exit code 137, 3 restarts | The container uses more memory than its **48Mi limit** (request is 32Mi), so the kernel kills it on each start. |

**Suggested fixes** (I can only read, so these are for you to do):
- **checkout:** put `DATABASE_URL` back, or roll back to revision 1 (`kubectl rollout undo deploy/checkout -n demo`).
- **frontend:** point the Deployment at a real nginx tag.
- **reports:** raise the memory limit. If the app really shouldn't need more than 48Mi, check it for a memory problem.

About 2m ago there were also `FailedScheduling` events for an untolerated node taint. All three current pods have been scheduled onto `squero-control-plane` since then, so that taint isn't the problem now. I didn't open past incident reports.

**Evidence**
- `kubernetes_list_deployments`: checkout, frontend, reports all 0/1 ready with Available=False MinimumReplicasUnavailable; frontend image nginx:1.99.99-does-not-exist
- `kubernetes_list_pods`: checkout pod terminated Error exit 1 (3 restarts); frontend pod Pending ErrImagePull 'nginx:1.99.99-does-not-exist: not found'; reports pod OOMKilled exit 137 (3 restarts)
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'FATAL: required env var DATABASE_URL is not set'
- `kubernetes_recent_changes`: checkout revision 2 rolled out 48s ago with env_removed: DATABASE_URL
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f: memory request 32Mi, limit 48Mi; state OOMKilled exit 137, restarts 3
- `kubernetes_get_events`: BackOff restarting checkout and reports containers; frontend ErrImagePull/ImagePullBackOff; earlier FailedScheduling (untolerated taint) ~2m ago, since resolved

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "demo"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 50}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
6. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
