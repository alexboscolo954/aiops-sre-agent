All three deployments in `demo` (checkout, frontend, reports) are unhealthy right now. Each shows 0/1 ready and `Available=False` with `MinimumReplicasUnavailable`. They have three separate causes.

1. **checkout** is crash-looping (exit 1, 3 restarts).
   - **Cause:** the app logs `FATAL: required env var DATABASE_URL is not set`.
   - **Trigger:** revision 2 rolled out about 48s before I checked, and it removed the `DATABASE_URL` env var. Revision 1 had it.
   - **Fix:** roll back to revision 1, or restore `DATABASE_URL` in the deployment. Per the runbook, don't just restart it.

2. **frontend** is stuck in `ErrImagePull`/`ImagePullBackOff`.
   - **Cause:** the image `nginx:1.99.99-does-not-exist` doesn't exist. The registry returns "not found".
   - **Note:** this was its first revision, so there is no earlier good revision to roll back to.
   - **Fix:** set a valid nginx tag.

3. **reports** is `OOMKilled` (exit 137, 3 restarts).
   - **Cause:** the memory limit is 48Mi. The app logs `building monthly report: loading 200MB of rows`, so it needs far more than the limit allows.
   - **Fix:** raise the memory limit and request to the observed peak plus about 25%, or change the app to stream or batch the rows. I did not measure actual usage, because no Prometheus tool was available.

All three pods also had a one-off `FailedScheduling` event about an untolerated node taint about 2m ago. They were later scheduled and started, so it is not the current cause.

**Evidence**
- `kubernetes_list_deployments`: checkout, frontend and reports all 0/1 ready with Available=False (MinimumReplicasUnavailable).
- `kubernetes_pod_logs`: checkout pod logs: 'FATAL: required env var DATABASE_URL is not set'.
- `kubernetes_recent_changes`: checkout revision 2 rolled out 48s before the check with env_removed: DATABASE_URL. The other deployments only show creation.
- `kubernetes_describe_deployment`: checkout revision 1 had env DATABASE_URL; revision 2 has none. The frontend image is nginx:1.99.99-does-not-exist and it has only revision 1.
- `kubernetes_get_events`: frontend: Failed to pull image nginx:1.99.99-does-not-exist (not found), then ErrImagePull and ImagePullBackOff. Back-off events for checkout and reports. One-off FailedScheduling (taint) on all three pods at about 2m.
- `kubernetes_describe_pod`: reports pod: memory limit 48Mi, last state OOMKilled exit 137, 3 restarts, BackOff events.
- `kubernetes_pod_logs`: reports pod logs: 'building monthly report: loading 200MB of rows'.
- `runbooks_read_runbook`: The oom-killed runbook says to raise the limit to observed peak plus 25% or fix the leak. The pod-crashlooping runbook says to roll back the bad revision or fix the config, and not to restart.

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 30}
4. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "tail_lines": 20}
6. `kubernetes_recent_changes` {"cluster": "kind"}
7. `incidents_search` {"keywords": "checkout reports frontend demo"}
8. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": "app=checkout"}
9. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
10. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
11. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": "app=frontend"}
12. `kubernetes_get_events` {"cluster": "kind", "namespace": "demo"}
13. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "frontend"}
14. `runbooks_search_runbooks` {"keywords": "oom memory"}
15. `runbooks_read_runbook` {"name": "oom-killed"}
16. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
17. `runbooks_read_runbook` {"name": "deployment-unavailable"}
18. `incidents_search` {"keywords": "DATABASE_URL OOMKilled ErrImagePull"}
19. `read_more` {"result_id": "none"}
20. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
21. `kubernetes_get_events` {"cluster": "kind", "namespace": "demo", "warnings_only": false}
22. `kubernetes_get_events` {"cluster": "kind", "namespace": "demo"}
23. `runbooks_read_runbook` {"name": "pod-crashlooping"}
24. `incidents_search` {"keywords": "checkout"}
25. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 60}
26. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"} (error)
