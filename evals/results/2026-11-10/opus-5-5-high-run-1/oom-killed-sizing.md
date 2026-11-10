## Pod lab/leaky-8555f7bc7c-mtzbj in the lab namespace keeps getting OOMKilled at its 256Mi memory limit (exit 137, 35 restarts). There has been no rollout in this deployment's single revision (1 day old). Repeated kills on an unchanged spec, plus an env var named LEAK_MIB_PER_MIN, point to a memory leak in the app rather than a limit that is simply too low.

**Root cause** (medium confidence, `app_error`): The 'app' container (python:3.12-alpine) is OOMKilled again and again at its 256Mi memory limit. Its last state was OOMKilled with exit code 137, it has restarted 35 times, and the Sizing puts peak usage at 255Mi, right at the limit. Nothing changed: the deployment has one revision, created 1 day ago, and no recent changes were found in the cluster. The env var LEAK_MIB_PER_MIN suggests the app is set up to grow its memory steadily, which would explain why memory climbs until the kernel kills it, whatever the limit is. This leak diagnosis is an inference from the env var name and the repeated kills. I have no memory-over-time metric and the previous logs were empty, so confidence is medium. Raising the limit to the Sizing's suggested 308Mi will only make the crashes less frequent.
**Severity:** medium  ·  **Affected:** lab/Deployment/leaky

**Evidence**
- `kubernetes_describe_pod`: Container 'app' last_state terminated OOMKilled, exit_code 137, restarts 35; limits memory 256Mi, requests 128Mi; env includes LEAK_MIB_PER_MIN; currently running since 27m
- `sizing_for_workload`: Memory peak 255Mi against a 256Mi limit; risk 'OOM-killed in 3 pods: its peak is its limit, not its demand'; suggested memory request/limit 308Mi
- `kubernetes_describe_deployment`: Only one revision (leaky-8555f7bc7c, created 1d ago), image python:3.12-alpine, unchanged since
- `kubernetes_recent_changes`: No rollouts or syncs in the last 360 minutes
- `kubernetes_pod_logs`: Logs from the previous (crashed) run were empty, so there is no app-level error output

**Recommendations**
1. Check memory growth over time for lab/leaky (container_memory_working_set_bytes) to confirm it climbs steadily until it hits 256Mi.
2. Check what LEAK_MIB_PER_MIN is set to in the deployment manifest. If it's an intentional leak setting (a test profile), set it to 0 or remove it. Otherwise, have the app owners profile the Python process and fix the leak.
3. As a temporary stopgap only, apply the Sizing's suggestion: memory request 308Mi and memory limit 308Mi for container 'app'. If the leak continues, this only delays the next OOM kill.
4. Lower the CPU request from 50m to about 24m, per the Sizing (p95 is 21m).

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj", "previous": true, "tail_lines": 50}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `sizing_for_workload` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "lab", "name": "leaky"}
