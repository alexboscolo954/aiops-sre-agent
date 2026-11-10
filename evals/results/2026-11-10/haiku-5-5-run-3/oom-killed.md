## Pod reports-55b4fffc66-hmq7f (demo) is crash looping with OOMKilled (exit 137) against a 48Mi memory limit. The reports deployment has a single revision (rev 1, created ~2m ago) and nothing in its config changed, so the limit looks too small for the job, which loads a 200MB dataset into memory.

**Root cause** (medium confidence, `resource_limits`): The reports container has a memory limit of 48Mi (request 32Mi). Its last state is OOMKilled with exit code 137, restarts=3, and the log line "building monthly report: loading 200MB of rows" shows the workload is designed to load about 200MB. A 48Mi limit cannot hold that, so the kernel kills the process each time it loads data. This is a limit set too low for a workload that needs far more memory. It is not a regression: there is only revision 1 and no env or image change. Confidence is medium because I have not measured actual memory use in Prometheus (none was queried).
**Severity:** high  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_describe_pod`: container app: limits memory 48Mi, requests 32Mi; last_state OOMKilled exit_code 137; restarts 3
- `kubernetes_pod_logs`: previous instance logs gone; latest instance log: 'building monthly report: loading 200MB of rows'
- `kubernetes_describe_deployment`: reports has a single revision (rev 1, created 2m ago), image python:3.12-alpine, env empty; Available=False MinimumReplicasUnavailable
- `kubernetes_recent_changes`: no reports rollout beyond revision 1 creation in the window; checkout rev 2 removed DATABASE_URL but is a different workload
- `runbooks_runbook_for_alert`: KubePodCrashLooping maps to pod-crashlooping, which points to oom-killed for OOMKilled exit 137

**Recommendations**
1. Check real memory use: query max by (pod) (container_memory_working_set_bytes{namespace="demo", pod=~"reports.*", container!=""}) in Prometheus. If it's near 48Mi, the limit is too small.
2. Raise the reports memory limit (and request) above the observed peak plus about 25%. The 200MB row load suggests a limit well above 256Mi, but confirm the number. Get approval before changing the deployment.
3. If the job can stream or chunk the 200MB load, change the code so it uses less memory instead of raising the limit.
4. Ignore the separate checkout (DATABASE_URL removed) and frontend (bad nginx tag) alerts in this namespace; they are different problems.

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true}
6. `incidents_search` {"keywords": "reports OOMKilled crashloop"}
7. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": "app=reports"}
8. `runbooks_read_runbook` {"name": "oom-killed"}
9. `TriageReport` {"summary": "Pod reports-55b4fffc66-hmq7f (demo) is crash looping with OOMKilled (exit 137) against a 48Mi memory limit. The reports deployment has a single revision (rev 1, created ~2m ago) and nothing in its config changed, so the limit looks too small for the job, which loads a 200MB dataset into
10. `TriageReport` {"summary": "Pod reports-55b4fffc66-hmq7f (demo) is crash looping with OOMKilled (exit 137) against a 48Mi memory limit. The reports deployment has a single revision (rev 1, created ~2m ago) and nothing in its config changed, so the limit looks too small for the job, which loads a 200MB dataset into
11. `TriageReport` {"summary": "Pod reports-55b4fffc66-hmq7f (demo) is crash looping with OOMKilled (exit 137) against a 48Mi memory limit. The reports deployment has a single revision (rev 1, created ~2m ago) and nothing in its config changed, so the limit looks too small for the job, which loads a 200MB dataset into
