## Pod leaky-8555f7bc7c-mtzbj is crash looping because it is OOMKilled at its 256Mi memory limit. It has restarted 35 times. Its memory use grows until the limit kills it.

**Root cause** (medium confidence, `app_error`): The container's memory grows until it reaches the 256Mi limit, and the kernel then OOM-kills it (exit 137). The Hub Sizing measured a peak of 255Mi, which is the limit rather than the real demand. It estimates the workload needs about 307Mi. The env var names LEAK_MIB_PER_MIN and MEMORY_MIB suggest a deliberate or accidental memory leak, but I could not confirm that: the logs were empty. No rollout caused it, since recent changes are empty and the pod is 1d old. Raising the limit would only delay the kills if memory really grows without bound.
**Severity:** medium  ·  **Affected:** lab/Deployment/leaky

**Evidence**
- `kubernetes_list_pods`: leaky-8555f7bc7c-mtzbj has 35 restarts, and its last termination was OOMKilled with exit code 137 27m ago. Other pods are stable.
- `kubernetes_describe_pod`: Container app has a memory request of 128Mi and a limit of 256Mi, with no liveness or readiness probes. Env vars include LEAK_MIB_PER_MIN and MEMORY_MIB. The only events are normal restarts.
- `sizing_for_workload`: Peak memory is 255Mi, equal to the 256Mi limit, so the pod was OOM-killed in 3 pods. The limit is below the 307Mi it needs. Suggested memory request and limit are 308Mi each.
- `kubernetes_recent_changes`: No rollouts in the window, so this is not a bad rollout.

**Recommendations**
1. Check the LEAK_MIB_PER_MIN and MEMORY_MIB settings and the application code for a memory leak. Fix the leak if it is real.
2. As a mitigation, raise the memory request and limit to 308Mi, as the Sizing suggests. Expect this to delay the OOM kills rather than stop them if the leak is unbounded.
3. Lower the CPU request from 50m to about 24m, since p95 usage is 21m.
4. Watch memory growth and restarts after the change. Add a memory-usage alert so the problem shows up before the limit is hit.

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "lab"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
3. `sizing_for_workload` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
4. `kubernetes_recent_changes` {"cluster": "kind"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj", "previous": true, "tail_lines": 30}
6. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj", "tail_lines": 30}
