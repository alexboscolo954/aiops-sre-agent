## Pod lab/leaky-8555f7bc7c-mtzbj has restarted 35 times. Each time it was OOMKilled (exit 137) at its 256Mi memory limit. Its config suggests a deliberate memory leak, so a bigger limit will only make it take longer to crash.

**Root cause** (medium confidence, `app_error`): The container gets OOMKilled when it reaches its 256Mi memory limit (measured peak 255Mi, 35 restarts). It has a LEAK_MIB_PER_MIN env var, which suggests memory grows steadily rather than settling at a fixed working set. If so, any limit will eventually be hit. This is inferred from the env var name and the repeated OOMs. I haven't confirmed the growth rate over time.
**Severity:** medium  ·  **Affected:** lab/Deployment/leaky

**Evidence**
- `kubernetes_describe_pod`: Container app: last state OOMKilled, exit code 137, 35 restarts, memory limit 256Mi, env includes LEAK_MIB_PER_MIN and MEMORY_MIB
- `sizing_for_workload`: Memory peak 255Mi against a 256Mi limit, OOM-killed in 3 pods. Suggested memory request and limit: 308Mi

**Recommendations**
1. Check the LEAK_MIB_PER_MIN setting or the app's memory growth. If the leak is unintended, fix the leak in the code.
2. As a stopgap, raise the memory request and limit to 308Mi as the Sizing suggests. If memory keeps growing, this only delays the OOM.
3. Watch memory usage over time after the change to confirm whether it levels off or keeps climbing.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
2. `sizing_for_workload` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
