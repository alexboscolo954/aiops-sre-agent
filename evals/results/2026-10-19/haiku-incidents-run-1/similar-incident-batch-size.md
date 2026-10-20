## Pod reports-55b4fffc66-hmq7f is crash looping because its app container is OOMKilled (exit 137) at a 48Mi memory limit. The job loads about 200MB of rows, so the limit is far too small. This is the only revision of the reports deployment, so no rollout caused it. A separate bad rollout of checkout (DATABASE_URL removed in revision 2) is also present but is not the alerted pod.

**Root cause** (high confidence, `resource_limits`): The reports container has memory limit 48Mi (request 32Mi) and last state is OOMKilled with exit code 137 on every restart (3 restarts). Its previous log shows 'building monthly report: loading 200MB of rows', so the workload needs far more than 48Mi. This is a healthy workload with limits set too low, not a leak or a new revision: the deployment has only revision 1, created 2m ago, with no env or image change. Probable cause is an undersized memory limit set at creation.
**Severity:** high  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: Running, 0/1 ready, restarts 3, last_terminated app OOMKilled exit 137.
- `kubernetes_describe_pod`: Container app (python:3.12-alpine) has requests memory 32Mi, limits memory 48Mi; state and last_state both OOMKilled exit code 137; events show BackOff restarting failed container app.
- `kubernetes_pod_logs`: Latest instance log (previous instance gone): 'building monthly report: loading 200MB of rows'. The process starts a 200MB load against a 48Mi limit.
- `kubernetes_describe_deployment`: reports has one rollout revision (revision 1, created 2m ago, image python:3.12-alpine, no env changes). Available=False, MinimumReplicasUnavailable, replicas ready 0 of 1.
- `kubernetes_recent_changes`: Only reports change in the window is 'reports revision 1 created 2m'. No rollout of reports or its dependencies preceded the crash loop.

**Recommendations**
1. Raise the reports container memory limit (and request) well above the observed peak of the 200MB row load, e.g. 256Mi limit with a matching request, or use the observed peak plus 25% per the oom-killed runbook. Confirm the peak with Prometheus container_memory_working_set_bytes for the pod if it is available.
2. Alternatively, change the job to stream rows in chunks so it does not hold 200MB in memory, then keep a modest limit.
3. After the change, confirm the pod goes Ready and restarts stop. Expect no further OOMKilled entries in last_terminated.
4. Separately, investigate the checkout deployment: revision 2 (rolled out 48s ago) removed the DATABASE_URL env var from container app, which is a bad_rollout. Roll back checkout to revision 1 or restore DATABASE_URL. This is outside this alert but is currently failing (checkout-869fc5bcc6-db5ps Error exit 1, 0/1 ready).
5. Also fix frontend: image nginx:1.99.99-does-not-exist does not exist (ErrImagePull). Correct the tag to a valid one.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": ""}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "container": "app", "previous": true, "tail_lines": 50}
