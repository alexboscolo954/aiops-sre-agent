## The reports pod (demo/reports-55b4fffc66-hmq7f) keeps getting OOMKilled (exit 137, 3 restarts) and is in a crash loop. Its memory limit is 48Mi, but on startup the process logs that it is "loading 200MB of rows". The deployment has never been ready (0/1).

**Root cause** (high confidence, `resource_limits`): The reports container has a 48Mi memory limit (32Mi request), but its job loads about 200MB of rows into memory to build the monthly report. The kernel kills it each time it goes over the limit (OOMKilled, exit 137). This is not a regression: the deployment has only one revision, created 2m ago, with the same 48Mi limit, so it has never run successfully at this size. No memory metrics were available, so the peak usage is inferred from the log line rather than measured.
**Severity:** medium  ·  **Affected:** demo/Deployment/reports

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: ready 0/1, 3 restarts, current and last state terminated OOMKilled, exit code 137
- `kubernetes_describe_pod`: Container app (python:3.12-alpine) has memory limit 48Mi, request 32Mi; BackOff warning 'Back-off restarting failed container app'
- `kubernetes_pod_logs`: Previous logs were gone, so this is the latest instance: 'building monthly report: loading 200MB of rows', which is far above the 48Mi limit
- `kubernetes_describe_deployment`: Only revision 1 (reports-55b4fffc66, created 2m ago), with the same 48Mi limit; Available=False, MinimumReplicasUnavailable. No earlier working revision to roll back to

**Recommendations**
1. Raise the memory limit and request on Deployment demo/reports to fit the dataset. With about 200MB loaded plus Python overhead, start with a limit around 320Mi and a request around 256Mi, then tune to observed peak plus 25% as the oom-killed runbook says.
2. Once memory metrics are available, check container_memory_working_set_bytes for the reports pod to confirm the peak and right-size the limit.
3. Longer term, have the report job stream or page through rows instead of loading the whole dataset into memory, so memory use doesn't grow with data size.
4. Don't restart the pod or roll back: a restart would hit the same limit, and there is no earlier revision to roll back to.
5. Other unhealthy pods in demo are separate problems and not part of this alert: checkout is exiting with Error (exit 1), and frontend can't start because the image tag nginx:1.99.99-does-not-exist is not found (ErrImagePull).

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f", "previous": true}
4. `incidents_search` {"keywords": "reports crash"}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "reports"}
