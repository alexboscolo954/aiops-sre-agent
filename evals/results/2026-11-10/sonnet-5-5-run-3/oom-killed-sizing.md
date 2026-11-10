## Pod leaky-8555f7bc7c-mtzbj in lab is crash looping because it is OOMKilled at its 256Mi memory limit. It has restarted 35 times. No recent rollout caused it.

**Root cause** (medium confidence, `app_error`): The leaky container's memory grows until it reaches the 256Mi limit, and the kernel OOM-kills it (exit 137). The deployment has a LEAK_MIB_PER_MIN env var, which points to a deliberate or real leak. The Hub Sizing shows peak usage of 255Mi against the 256Mi limit, so the peak is the limit and not the real demand. It estimates the workload needs about 307Mi. The limit is therefore too low, but a larger limit would only delay the kill if the leak is unbounded. No logs were available from the previous run, and there are no recent rollouts.
**Severity:** medium  ·  **Affected:** lab/Deployment/leaky

**Evidence**
- `kubernetes_list_pods`: leaky-8555f7bc7c-mtzbj has 35 restarts. Its last termination was OOMKilled with exit code 137, 27m ago. The other pods show only 3 restarts, with exit code 255 about 9h ago.
- `kubernetes_describe_pod`: The container has a memory request of 128Mi and a limit of 256Mi, with no probes. The env var names include MEMORY_MIB and LEAK_MIB_PER_MIN. The last state is OOMKilled.
- `sizing_for_workload`: Memory peak is 255Mi against a 256Mi limit. Risks: OOM-killed in 3 pods, and the limit is below the 307Mi it needs. Suggested memory request and limit are both 308Mi.
- `kubernetes_recent_changes`: No rollouts or changes were found, so a new revision is not the cause.

**Recommendations**
1. Check the app's memory-growth settings (LEAK_MIB_PER_MIN, MEMORY_MIB). Find out whether the leak is intended, for example in a test workload, or a real bug.
2. If the leak is a real bug, fix it in the code. Raising limits alone will not stop the restarts if memory grows without bound.
3. As a stopgap, raise the memory request and limit to the Hub's suggested 308Mi (request and limit both 308Mi). Do this through the deployment manifest or GitOps.
4. Watch memory and restart counts after the change. If the OOM kills continue at the higher limit, treat it as a leak.

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "lab"}
2. `kubernetes_recent_changes` {"cluster": "kind"}
3. `sizing_for_workload` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj", "previous": true, "tail_lines": 30}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
