## The pod lab/leaky-8555f7bc7c-mtzbj has restarted 35 times. Its last exit was OOMKilled (exit 137) at its 256Mi memory limit. The image hasn't changed, there has been only one rollout (1 day ago), and the container sets LEAK_MIB_PER_MIN, so memory most likely keeps growing until it hits the limit.

**Root cause** (medium confidence, `app_error`): The app container's memory climbs until the kernel kills it at its 256Mi limit. The Hub Sizing measured peak memory at 255Mi, right at the limit, and saw OOM kills in 3 pods. Nothing was rolled out recently: revision 1 is the only one, created 1d ago, with the same image (python:3.12-alpine). The container gets an env var named LEAK_MIB_PER_MIN, which points to memory that grows over time (a leak) rather than a fixed limit that is simply too small. Env values aren't visible, so the leak is inferred from the name plus the repeated OOM pattern. If that's right, a bigger limit only pushes the next kill further out.
**Severity:** medium  ·  **Affected:** lab/Deployment/leaky

**Evidence**
- `kubernetes_describe_pod`: Container app: restarts 35, last_state terminated OOMKilled exit_code 137, limits memory 256Mi, requests 128Mi; env includes MEMORY_MIB and LEAK_MIB_PER_MIN
- `kubernetes_describe_deployment`: Only rollout revision 1 (leaky-8555f7bc7c), created 1d ago, image python:3.12-alpine: no recent change
- `sizing_for_workload`: Memory peak 255Mi at the 256Mi limit; 'OOM-killed in 3 pods: its peak is its limit, not its demand'; suggested memory request/limit 308Mi
- `kubernetes_pod_logs`: Previous-run logs for leaky-8555f7bc7c-mtzbj came back empty: the app logged nothing before being OOM-killed

**Recommendations**
1. Check the LEAK_MIB_PER_MIN and MEMORY_MIB values in the leaky Deployment manifest. If the leak is intended (a test workload), this alert is expected and can be silenced or the workload removed.
2. If it's a real service, have the app owners find and fix the memory leak. That is the actual fix.
3. Meanwhile, apply the Hub Sizing suggestion: memory request and limit 308Mi (now 128Mi/256Mi). This gives more time between OOM kills but won't stop them while memory keeps growing.
4. Optionally lower the CPU request from 50m to about 24m (p95 21m), per the Sizing.
5. Add memory-usage monitoring, such as a working-set growth alert, to catch leaks before OOM kills.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj", "previous": true, "tail_lines": 50}
3. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "lab", "name": "leaky"}
4. `sizing_for_workload` {"cluster": "kind", "namespace": "lab", "name": "leaky"}
