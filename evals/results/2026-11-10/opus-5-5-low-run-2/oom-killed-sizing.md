## Pod lab/leaky-8555f7bc7c-mtzbj keeps getting OOMKilled (exit 137) at its 256Mi memory limit and has restarted 35 times. Its env var LEAK_MIB_PER_MIN, and the name, suggest memory grows steadily over time, so this looks like a leak rather than a limit that is simply too small.

**Root cause** (medium confidence, `app_error`): The container's memory climbs until it reaches the 256Mi limit and the kernel kills it (OOMKilled, exit 137). Measured peak is 255Mi, which is just the limit. The workload is configured with a LEAK_MIB_PER_MIN env var, so memory most likely grows without bound and any limit will eventually be hit. I did not read logs or memory metrics over time, so the leak is inferred from the config and the crash pattern.
**Severity:** medium  ·  **Affected:** lab/Deployment/leaky

**Evidence**
- `kubernetes_describe_pod`: container app last terminated OOMKilled exit 137, 35 restarts, limit memory 256Mi, request 128Mi; env includes LEAK_MIB_PER_MIN
- `sizing_for_workload`: peak 255Mi = 256Mi limit; OOM-killed in 3 pods; suggested memory request/limit 308Mi

**Recommendations**
1. Check the LEAK_MIB_PER_MIN setting and the app's memory growth. If this leak simulation isn't wanted, set it to 0 or fix the leak in the code.
2. As a stopgap, raise the memory request and limit to the 308Mi the Sizing suggests. This will only delay the OOM kills if memory keeps growing.
3. After the change, watch memory use over time to confirm it levels off.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
2. `sizing_for_workload` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
