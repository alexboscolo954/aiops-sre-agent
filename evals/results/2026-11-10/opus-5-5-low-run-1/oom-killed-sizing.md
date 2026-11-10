## Pod lab/leaky-8555f7bc7c-mtzbj keeps getting OOMKilled at its 256Mi memory limit (exit 137, 35 restarts). Its memory grows steadily until it hits the limit, which points to a leak rather than a limit that is simply too small.

**Root cause** (medium confidence, `app_error`): The app container's memory climbs until it reaches the 256Mi limit (measured peak 255Mi) and the kernel kills it (OOMKilled, exit 137). The pod's env includes LEAK_MIB_PER_MIN, which suggests the workload is set up to leak memory at a fixed rate, so any limit will eventually be reached. This is inferred from the env var name and the kill-at-the-limit pattern; I did not read the logs or measure the growth rate directly.
**Severity:** medium  ·  **Affected:** lab/Deployment/leaky

**Evidence**
- `kubernetes_describe_pod`: Container app: last_state OOMKilled exit 137, 35 restarts, memory limit 256Mi, env includes LEAK_MIB_PER_MIN
- `sizing_for_workload`: Memory peak 255Mi against a 256Mi limit, OOM-killed in 3 pods; suggested request and limit 308Mi

**Recommendations**

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
2. `sizing_for_workload` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
