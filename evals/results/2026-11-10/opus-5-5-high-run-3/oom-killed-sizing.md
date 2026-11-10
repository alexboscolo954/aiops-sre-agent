## The app container in lab/leaky (pod leaky-8555f7bc7c-mtzbj) keeps getting OOMKilled (exit 137) when it reaches its 256Mi memory limit. It has restarted 35 times, and nothing has changed in the cluster recently. Memory peaks right at the limit and the pod's settings point to a deliberate memory leak, so this looks like a leak in the app, not just a limit that is set too low.

**Root cause** (medium confidence, `app_error`): The app container in Deployment lab/leaky uses more and more memory until it hits its 256Mi limit and the kernel kills it (last state OOMKilled, exit code 137, 35 restarts). The Sizing shows peak memory of 255Mi, effectively the limit, and OOM kills in 3 pods. The deployment has had a single revision (1d old) and the cluster shows no recent changes, so a rollout did not cause this. Why I think it's a leak: the workload is named 'leaky' and has an env var called LEAK_MIB_PER_MIN, which suggests it is built to leak memory at a steady rate. I could not see that variable's value, and the crashed run left no logs, so this part is inferred. If memory keeps growing, raising the limit to the suggested 308Mi only buys time before the next OOM kill.
**Severity:** medium  ·  **Affected:** lab/Deployment/leaky

**Evidence**
- `kubernetes_describe_pod`: Container app: last_state terminated OOMKilled, exit_code 137, restarts 35, memory limit 256Mi, request 128Mi; env vars include LEAK_MIB_PER_MIN and MEMORY_MIB
- `sizing_for_workload`: Memory peak 255Mi against a 256Mi limit; risks: 'OOM-killed in 3 pods: its peak is its limit, not its demand', 'memory limit 256Mi is below the 307Mi it needs'; suggested memory request and limit 308Mi
- `kubernetes_describe_deployment`: Only rollout revision 1 (ReplicaSet leaky-8555f7bc7c), created 1d ago, image python:3.12-alpine; no recent revision changes
- `kubernetes_recent_changes`: No rollouts or changes in the cluster in the last 360 minutes
- `kubernetes_pod_logs`: The previous (crashed) run left no log output, so there is no error message to read

**Recommendations**
1. Find out whether the leak is intended: check the value of LEAK_MIB_PER_MIN (and MEMORY_MIB) in the Deployment manifest. If it is above zero, memory keeps growing and no limit will stop the restarts.
2. If this is a real workload, fix the memory growth in the app (profile memory over time, or set LEAK_MIB_PER_MIN to 0 if it's a test knob).
3. As a stopgap, set the memory request and limit to 308Mi as the Sizing suggests, so the pod lasts longer between OOM kills. Expect it to still be killed if memory keeps growing.
4. Optionally lower the CPU request from 50m to about 24m: the Sizing measured a p95 of 21m.
5. Watch the container's memory and restart count after the change, to see whether usage levels off below the new limit.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj", "previous": true, "tail_lines": 50}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `sizing_for_workload` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "lab", "name": "leaky"}
