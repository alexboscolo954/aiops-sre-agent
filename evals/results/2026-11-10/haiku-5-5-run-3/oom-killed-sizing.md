## Pod leaky-8555f7bc7c-mtzbj is crash looping because its single container is repeatedly OOM-killed (exit 137) at its 256Mi memory limit. The workload has one revision that has not changed in about a day, so this is a memory-limit problem against a leaking app, not a bad rollout.

**Root cause** (medium confidence, `resource_limits`): The container's memory limit of 256Mi is below what the app needs. The Hub Sizing records peak memory of 255Mi, which is pinned at the limit, and 307Mi needed. The pod shows last_state OOMKilled with exit code 137 and 35 restarts. The app's env includes LEAK_MIB_PER_MIN, which suggests it leaks memory steadily until the kernel kills it. The deployment has only revision 1 (created 1d ago) and no recent changes were found in the lab namespace, so a rollout did not cause this.
**Severity:** high  ·  **Affected:** lab/Deployment/leaky

**Evidence**
- `kubernetes_describe_pod`: Pod leaky-8555f7bc7c-mtzbj container app: last_state terminated OOMKilled, exit_code 137, restarts 35; requests memory 128Mi, limit 256Mi; env includes LEAK_MIB_PER_MIN.
- `sizing_for_workload`: Deployment leaky: memory peak 255Mi against 256Mi limit; risks 'OOM-killed in 3 pods', 'memory limit 256Mi is below the 307Mi it needs'; suggested memory_request 308Mi and memory_limit 308Mi.
- `kubernetes_describe_deployment`: Deployment leaky has one rollout revision (revision 1, ReplicaSet leaky-8555f7bc7c, created 1d ago); image python:3.12-alpine; Available and Progressing True.
- `kubernetes_recent_changes`: No rollouts or changes in the lab namespace in the last 180 minutes.
- `kubernetes_pod_logs`: Previous container logs returned no output, so the app itself logged nothing before the kill.

**Recommendations**
1. Raise the memory request and limit of deployment leaky in lab to about 308Mi each, as the Sizing suggests. Get the change approved before applying it.
2. Confirm the growth is a leak: check the LEAK_MIB_PER_MIN setting and whether memory keeps rising past the new limit. If it does, the real fix is in the app or the test profile, not just the limit.
3. Watch restarts and memory usage after the change to confirm the CrashLoopBackOff stops.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj", "previous": true}
3. `sizing_for_workload` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "lab", "name": "leaky"}
5. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 180}
6. `TriageReport` {"summary": "Pod leaky-8555f7bc7c-mtzbj is crash looping because its single container is repeatedly OOM-killed (exit 137) at its 256Mi memory limit. The workload has one revision that has not changed in about a day, so this is a memory-limit problem against a leaking app, not a bad rollout.", "categ
