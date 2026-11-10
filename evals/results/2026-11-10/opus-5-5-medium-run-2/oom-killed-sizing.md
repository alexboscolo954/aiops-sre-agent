## Pod lab/leaky-8555f7bc7c-mtzbj keeps getting OOMKilled at its 256Mi memory limit (exit 137, 35 restarts). Memory climbs until it hits the limit, which looks like a memory leak (the workload sets LEAK_MIB_PER_MIN). Nothing changed recently: the Deployment has had one revision for 1 day.

**Root cause** (medium confidence, `app_error`): Container 'app' (python:3.12-alpine) uses more and more memory until the kernel kills it at its 256Mi limit. Last state: OOMKilled, exit code 137, 35 restarts. The Sizing measured peak usage at 255Mi, right at the limit, and found OOM kills in 3 pods. The Deployment sets an env var named LEAK_MIB_PER_MIN, which suggests the app is set up to leak memory at a fixed rate. I can't confirm that because env values aren't returned. A recent change didn't cause this: there is only revision 1, created 1d ago. The previous run left no logs. If the memory really grows without bound, raising the limit only delays the next kill; it doesn't stop it.
**Severity:** medium  ·  **Affected:** lab/Deployment/leaky

**Evidence**
- `kubernetes_describe_pod`: Container app: last_state terminated OOMKilled, exit_code 137, finished 27m ago; 35 restarts; limits memory 256Mi, requests 128Mi; env includes LEAK_MIB_PER_MIN
- `sizing_for_workload`: Memory peak 255Mi against a 256Mi limit; risks: OOM-killed in 3 pods, limit is below the 307Mi it needs; suggested memory request and limit 308Mi
- `kubernetes_describe_deployment`: Only rollout revision 1 (leaky-8555f7bc7c), created 1d ago, so no recent rollout
- `kubernetes_pod_logs`: Previous container run left no log output

**Recommendations**
1. Check the value of LEAK_MIB_PER_MIN in the leaky Deployment and the app's memory behavior. If the leak is not intended, set it to 0 or fix the code that keeps holding memory.
2. As a short-term fix, raise the memory request and limit to the Sizing's suggested 308Mi. If memory keeps growing this only spaces out the OOM kills.
3. Track container memory over time (e.g. container_memory_working_set_bytes) to confirm it grows steadily instead of levelling off at a stable size.
4. Silence or downgrade the alert if this is a deliberate leak test workload in the lab namespace.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj", "previous": true, "tail_lines": 50}
3. `sizing_for_workload` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "lab", "name": "leaky"}
