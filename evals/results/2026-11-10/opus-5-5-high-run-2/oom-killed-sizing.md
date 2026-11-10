## Pod lab/leaky-8555f7bc7c-mtzbj keeps getting OOMKilled at its 256Mi memory limit (exit 137, 35 restarts on revision 1, which is about 1 day old). Nothing was rolled out recently. The pattern looks like a memory leak: the workload is called 'leaky' and has a LEAK_MIB_PER_MIN setting, so a bigger limit alone would only delay the next OOM.

**Root cause** (medium confidence, `app_error`): The 'app' container's memory keeps growing until it hits its 256Mi limit and the kernel OOM-kills it (last state terminated OOMKilled, exit code 137, 35 restarts). The Sizing measured peak memory at 255Mi, right at the limit, so the limit is capping the usage rather than showing what the app actually needs. Nothing changed recently: the deployment has only revision 1 (1 day old) and kubernetes_recent_changes is empty. The container has env vars MEMORY_MIB and LEAK_MIB_PER_MIN, which points to memory growing over time (a leak) rather than a steady working set that is a bit too big. Env var values are not visible to me, so I'm inferring the leak from the env var names and the repeating OOM pattern, not from logs; the previous logs were empty.
**Severity:** medium  ·  **Affected:** lab/Deployment/leaky

**Evidence**
- `kubernetes_describe_pod`: Container 'app' (python:3.12-alpine): last_state terminated OOMKilled, exit_code 137, restarts 35. Memory request 128Mi, limit 256Mi. Env vars include MEMORY_MIB and LEAK_MIB_PER_MIN. No liveness or readiness probes.
- `kubernetes_pod_logs`: Previous container logs for leaky-8555f7bc7c-mtzbj were empty, so there is no app-level error output; the container was killed by the OOM killer.
- `sizing_for_workload`: Memory peak 255Mi against a 256Mi limit. Risks: 'OOM-killed in 3 pods: its peak is its limit, not its demand' and 'memory limit 256Mi is below the 307Mi it needs'. Suggested memory request and limit: 308Mi each.
- `kubernetes_describe_deployment`: Only rollout revision 1 (ReplicaSet leaky-8555f7bc7c, created 1d ago, image python:3.12-alpine); no recent revision to blame.
- `kubernetes_recent_changes`: No rollouts or syncs in the last 360 minutes.

**Recommendations**
1. Check what LEAK_MIB_PER_MIN and MEMORY_MIB are set to in the leaky Deployment spec. If the leak is on purpose (a lab or demo setting), set LEAK_MIB_PER_MIN to 0 or remove it; otherwise get the app owners to fix the memory growth in the code.
2. Short-term fix to make the OOM kills less frequent: set the 'app' container's memory request and limit to 308Mi, per the Sizing. If the leak is real, this only delays the OOM.
3. Once fixed, watch the container's memory over time to confirm it levels off instead of climbing toward the limit, and that the restart count stops rising.
4. Optionally lower the CPU request from 50m to about 24m: the Sizing measured p95 at 21m and flags 26m of waste.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj", "previous": true, "tail_lines": 50}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `sizing_for_workload` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "lab", "name": "leaky"}
