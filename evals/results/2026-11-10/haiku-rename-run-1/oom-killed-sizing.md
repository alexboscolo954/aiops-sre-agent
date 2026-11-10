## Pod leaky-8555f7bc7c-mtzbj is crash looping because its app container is OOM-killed at its 256Mi memory limit (exit 137, 35 restarts). The workload is a deliberate memory leak, so raising the limit only delays the next kill. No rollout happened in the last 360 minutes.

**Root cause** (medium confidence, `app_error`): The app container is OOMKilled at its memory limit of 256Mi (last_state exit_code 137, restarts 35). The container's env includes LEAK_MIB_PER_MIN, so the process grows memory until the kernel kills it. The Hub measured a peak of 255Mi, which equals the limit, and it suggests about 308Mi. Memory request is 128Mi. No recent rollout explains this, so the leak is the likely cause. Pod logs were empty, so the leak itself is not confirmed in logs.
**Severity:** high  ·  **Affected:** lab/Deployment/leaky

**Evidence**
- `kubernetes_describe_pod`: Container app (python:3.12-alpine): last_state terminated OOMKilled, exit_code 137, restarts 35; limits memory 256Mi, requests memory 128Mi; env names include LEAK_MIB_PER_MIN and MEMORY_MIB; pod Ready=True, currently running 27m.
- `sizing_for_workload`: Deployment leaky, container app: memory peak 255Mi against limit 256Mi; risks say 'OOM-killed in 3 pods: its peak is its limit, not its demand'; suggested memory_request and memory_limit 308Mi.
- `kubernetes_recent_changes`: No rollouts or changes in the last 360 minutes in namespace lab, so no recent revision is implicated.
- `kubernetes_pod_logs`: Previous container logs were empty, so no application error message was captured.

**Recommendations**
1. Treat the immediate fix as a mitigation: raise the app container's memory request and limit to about 308Mi per the Sizing suggestion, which stops the restart loop for now.
2. Confirm the leak: check LEAK_MIB_PER_MIN and PROFILE on the leaky Deployment. If the leak is intentional for testing, document it. If not, fix the code path that retains memory.
3. Watch memory over time after the change to confirm growth is bounded, and set an alert on container memory approaching its limit.
4. Escalate to the owning team of lab/Deployment/leaky if the leak is unintended.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj", "container": null, "tail_lines": 100, "previous": true}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `sizing_for_workload` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj", "kind": null}
