## Pod leaky-8555f7bc7c-mtzbj has restarted 35 times and its last termination was OOMKilled (exit 137). Its memory use reaches the 256Mi limit.

**Root cause** (medium confidence, `resource_limits`): The app container's memory limit is 256Mi and its request is 128Mi. The Hub measured a peak of 255Mi, which is the limit itself, so the real demand is higher. Sizing puts the need at about 307Mi, so the kernel OOM-kills the container repeatedly. No rollout happened recently, so this is not a regression from a change. I could not read the crashed container's logs, so I can't rule out a memory leak. The workload name suggests one, but nothing I saw confirms it. If usage keeps growing after the limit is raised, treat it as an app bug.
**Severity:** medium  ·  **Affected:** lab/Deployment/leaky

**Evidence**
- `kubernetes_list_pods`: leaky-8555f7bc7c-mtzbj has 35 restarts, with last_terminated OOMKilled, exit code 137, 27m ago. Other pods are stable at 3 restarts, with the last termination 9h ago.
- `sizing_for_workload`: Memory limit 256Mi and request 128Mi against a peak of 255Mi. Risks: OOM-killed in 3 pods, and the limit is below the 307Mi it needs. Suggested memory request and limit: 308Mi.
- `kubernetes_recent_changes`: No rollouts in the window, so no recent change explains the crashes.

**Recommendations**
1. Raise the leaky container's memory request and limit to 308Mi, as the Hub Sizing suggests.
2. Watch memory after the change. If it keeps growing towards the new limit, profile the app for a leak and fix the code.
3. Lower the CPU request from 50m to about 24m (p95 is 21m) to cut waste.
4. Check the previous container logs if they are still available, to confirm the OOM and look for allocation errors.

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "lab"}
2. `kubernetes_recent_changes` {"cluster": "kind"}
3. `sizing_for_workload` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj", "previous": true, "tail_lines": 30}
