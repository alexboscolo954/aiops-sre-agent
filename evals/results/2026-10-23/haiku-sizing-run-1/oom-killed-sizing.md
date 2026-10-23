## Pod leaky-8555f7bc7c-mtzbj is crash looping because its app container is repeatedly OOMKilled (exit 137) at the 256Mi memory limit, with 35 restarts. The Sizing shows the workload peaks at its limit, which points to a memory leak rather than a recent rollout; the deployment has only one revision and no changes in the last 6 hours.

**Root cause** (medium confidence, `app_error`): The container is OOMKilled at its 256Mi memory limit (last_state terminated OOMKilled, exit code 137, 35 restarts). The Sizing reports a peak of 255Mi against the 256Mi limit and says the workload needs about 307Mi. The deployment has a single revision (revision 1, created 1d ago) and kubernetes_recent_changes returned no rollouts, so no new revision caused this. The container's env includes LEAK_MIB_PER_MIN, which suggests the app allocates memory that is never released, so usage grows until the limit kills it. Raising the limit only delays the next OOM kill. Previous-container logs were empty, so the leak itself is not confirmed in logs.
**Severity:** high  ·  **Affected:** lab/Deployment/leaky

**Evidence**
- `kubernetes_describe_pod`: Pod leaky-8555f7bc7c-mtzbj: container app, memory limit 256Mi, last_state terminated OOMKilled exit_code 137, restarts 35, currently running for 27m; Ready=True. Env includes LEAK_MIB_PER_MIN.
- `sizing_for_workload`: kind/lab/Deployment/leaky container app: memory peak 255Mi against limit 256Mi; risks say 'OOM-killed in 3 pods' and 'memory limit 256Mi is below the 307Mi it needs'; suggested memory_request 308Mi and memory_limit 308Mi.
- `kubernetes_describe_deployment`: Deployment leaky has one rollout revision (revision 1, ReplicaSet leaky-8555f7bc7c, created 1d ago, image python:3.12-alpine); Available=True, 1/1 ready.
- `kubernetes_recent_changes`: No rollouts or changes in any namespace in the last 360 minutes.
- `kubernetes_pod_logs`: Previous-container logs (tail 100) returned no output, so the crash cause could not be read from logs.

**Recommendations**
1. Confirm the leak pattern from the app's memory metrics or the LEAK_MIB_PER_MIN setting, since the logs are empty.
2. As a temporary mitigation, with human approval, raise the memory limit and request to about 308Mi as the Sizing suggests (memory request 308Mi, limit 308Mi). This stops the crash loop but does not fix the leak.
3. Fix the leak in the application, or stop the leak-generating behaviour (for example LEAK_MIB_PER_MIN or PROFILE), then verify memory stays flat over time.
4. Watch restarts and memory usage after the change to confirm the OOM kills stop.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj", "container": null, "tail_lines": 100, "previous": true}
3. `sizing_for_workload` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj", "kind": null}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "lab", "name": "leaky"}
5. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
