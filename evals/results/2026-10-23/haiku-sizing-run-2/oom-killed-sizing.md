## Pod leaky-8555f7bc7c-mtzbj is in a CrashLoop because its app container is repeatedly OOMKilled (exit 137) at its 256Mi memory limit, with 35 restarts. The workload is a single-revision Deployment that has been running for about a day, so no rollout caused this. Raising the limit will only delay the kill if the process keeps leaking memory.

**Root cause** (medium confidence, `app_error`): The app container hits its 256Mi memory limit and is OOMKilled (last_state OOMKilled, exit 137, restarts 35). The Deployment has only revision 1 (1d old), so no recent change caused it. The container is configured with LEAK_MIB_PER_MIN and MEMORY_MIB env vars, which points to a leaking workload. Sizing reports peak memory of 255Mi against a 256Mi limit and says the workload needs about 307Mi. The memory request is 128Mi, well below what it actually uses. The suggested fix is a 308Mi request and limit, but this is a sizing fix that buys time, not a fix for the leak itself.
**Severity:** high  ·  **Affected:** lab/Deployment/leaky, lab/Pod/leaky-8555f7bc7c-mtzbj

**Evidence**
- `kubernetes_describe_pod`: Container app (python:3.12-alpine): limits memory 256Mi, requests memory 128Mi, last_state terminated OOMKilled exit_code 137, restarts 35, running_since 27m. Pod is Ready, and the events show repeated Created/Started cycles.
- `kubernetes_list_pods`: leaky-8555f7bc7c-mtzbj restarts 35, last terminated OOMKilled exit 137. The other lab pods show restarts 3 from an earlier event 9h ago, not from this pod.
- `sizing_for_workload`: kind/lab/Deployment/leaky: memory peak 255Mi against a 256Mi limit. Risks: OOM-killed in 3 pods, limit 256Mi is below the 307Mi needed, request 128Mi is below 256Mi. Suggested memory_request and memory_limit are 308Mi, because the peak equals the limit.
- `kubernetes_describe_deployment`: Deployment leaky has 1 desired and 1 ready replica, and rollout_history contains only revision 1 (ReplicaSet leaky-8555f7bc7c, created 1d ago). Env vars include LEAK_MIB_PER_MIN and MEMORY_MIB, and there is no recent rollout.

**Recommendations**
1. Confirm the leak with the app owner: check LEAK_MIB_PER_MIN and MEMORY_MIB in the Deployment spec, and confirm whether the growth is intended for this test workload.
2. Apply the Sizing suggestion, raising the memory request and limit to 308Mi (requires human approval since it changes the Deployment), to stop the crash loop short-term.
3. If the leak is not intended, fix the application's memory growth and then re-verify the limit against measured steady-state usage.
4. Monitor restarts and memory usage after the change. If memory keeps rising toward the new limit, the leak will OOM again.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "lab", "label_selector": ""}
3. `sizing_for_workload` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj", "kind": null}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "lab", "name": "leaky"}
