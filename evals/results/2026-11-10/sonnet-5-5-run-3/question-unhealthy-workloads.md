All three deployments in `demo` are unhealthy. Each is at 0/1 ready and reports `Available=False (MinimumReplicasUnavailable)`. The causes are different:

1. **checkout** is crash-looping (exit 1, 3 restarts).
   - Cause: the `DATABASE_URL` env var is missing. The log says `FATAL: required env var DATABASE_URL is not set`.
   - Revision 2 of the deployment rolled out about 48s ago and removed `DATABASE_URL` from the `app` container. Revision 1 had it.
   - Fix: roll back to revision 1, or restore `DATABASE_URL` in the deployment config. Restarting the pod won't help.

2. **frontend** is stuck in `ErrImagePull`/`ImagePullBackOff` and the pod is Pending.
   - Cause: the image `nginx:1.99.99-does-not-exist` doesn't exist. The registry returns `not found`.
   - This has been the only revision since creation, so it never worked.
   - Fix: set a valid nginx tag.

3. **reports** is crash-looping with `OOMKilled` (exit 137, 3 restarts).
   - Cause: the memory limit is 48Mi, and the app logs `building monthly report: loading 200MB of rows`. That is far above the limit.
   - This has been the only revision since creation.
   - Fix: raise the memory limit and request well above the real peak (the oom-killed runbook suggests observed peak plus 25%), or change the app to stream or paginate the rows. I did not check actual memory usage because no Prometheus tool is available.

Earlier `FailedScheduling` warnings (untolerated taint) appeared on all three about 2 minutes ago. The pods have since been scheduled, so they aren't the current cause. No past incidents matched these workloads.

**Evidence**
- `kubernetes_list_pods`: checkout pod 0/1, Error exit 1, 3 restarts. frontend pod Pending, ErrImagePull for nginx:1.99.99-does-not-exist (not found). reports pod 0/1, OOMKilled exit 137, 3 restarts.
- `kubernetes_list_deployments`: checkout, frontend and reports all 0/1 ready with Available=False MinimumReplicasUnavailable.
- `kubernetes_pod_logs`: checkout log: 'FATAL: required env var DATABASE_URL is not set'.
- `kubernetes_recent_changes`: checkout revision 2 rolled out 48s ago with env_removed: app: [DATABASE_URL].
- `kubernetes_describe_deployment`: checkout revision 1 had env DATABASE_URL, revision 2 has none. frontend uses image nginx:1.99.99-does-not-exist (revision 1 only). reports has a 48Mi memory limit (revision 1 only).
- `kubernetes_describe_pod`: reports container limit memory 48Mi, last state OOMKilled exit 137, BackOff events.
- `kubernetes_get_events`: frontend: Failed to pull image nginx:1.99.99-does-not-exist ... not found (ErrImagePull/ImagePullBackOff). BackOff events on checkout and reports. FailedScheduling taint warnings were from about 2m ago.
- `runbooks_read_runbook`: oom-killed runbook: exit 137 means the memory limit was exceeded. Raise the limit to observed peak plus 25% or fix the leak.

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 30}
4. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "tail_lines": 20}
6. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 120}
7. `incidents_search` {"keywords": "checkout reports frontend demo"}
8. `runbooks_search_runbooks` {"keywords": "oom"}
9. `runbooks_read_runbook` {"name": "oom-killed"}
10. `read_more` {"result_id": "none"}
11. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
12. `kubernetes_get_events` {"cluster": "kind", "namespace": "demo"}
13. `kubernetes_get_events` {"cluster": "kind", "namespace": "demo", "warnings_only": true}
14. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "frontend"}
15. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
16. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
17. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": "app=frontend"}
18. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": "app=checkout"}
19. `runbooks_read_runbook` {"name": "pod-crashlooping"}
20. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
21. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
22. `kubernetes_get_events` {"cluster": "kind", "namespace": "demo", "warnings_only": false}
23. `read_more` {"result_id": "x"}
