## The leaky container in lab/leaky-8555f7bc7c-mtzbj has been OOMKilled (exit 137) and restarted 35 times. Each time, memory climbs to the 256Mi limit, which looks like a memory leak. Nothing was rolled out: the deployment has had one revision for a day.

**Root cause** (medium confidence, `app_error`): Container 'app' (python:3.12-alpine) keeps climbing to its 256Mi memory limit (measured peak 255Mi) and gets OOMKilled (exit 137, 35 restarts). It is the deployment's only revision, about 1 day old, so no rollout caused this. The container has an env var named LEAK_MIB_PER_MIN, and memory grows until it hits the limit after every restart. Together these point to steady leak-style growth rather than a fixed working set that is slightly too big. Raising the limit only buys time. This is inferred: the crashed run left no logs, and env values can't be read.
**Severity:** medium  ·  **Affected:** lab/Deployment/leaky

**Evidence**
- `kubernetes_describe_pod`: Container app: last_state terminated OOMKilled, exit_code 137, 35 restarts. Limits memory 256Mi, request 128Mi. Env includes LEAK_MIB_PER_MIN.
- `kubernetes_describe_deployment`: Only one revision (leaky-8555f7bc7c, created 1d ago), so no recent rollout. Deployment shows 1/1 ready between crashes.
- `sizing_for_workload`: Memory peak 255Mi against a 256Mi limit. Risks: 'OOM-killed in 3 pods: its peak is its limit, not its demand'. Suggested memory request/limit 308Mi/308Mi.
- `kubernetes_pod_logs`: No logs from the previous (crashed) run, so there is no application error to confirm the cause.

**Recommendations**
1. Check the LEAK_MIB_PER_MIN value in the deployment manifest. If the leak is intentional (a lab test) or set by mistake, set it to 0 or remove it.
2. Short term, raise memory to the Hub Sizing's suggestion, request 308Mi and limit 308Mi, to cut how often it crashes. A leak will still hit the new limit eventually.
3. Profile the app's memory over time (for example, container_memory_working_set_bytes) to confirm steady growth, then fix the leak in the code.
4. Optionally lower the CPU request from 50m to about 24m. Measured p95 CPU is 21m.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj", "previous": true, "tail_lines": 50}
3. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "lab", "name": "leaky"}
4. `sizing_for_workload` {"cluster": "kind", "namespace": "lab", "name": "leaky"}
