## Pod leaky-8555f7bc7c-mtzbj is crash looping because its single container is repeatedly OOMKilled at its 256Mi memory limit (35 restarts). The workload is a leaking process, not a bad rollout: there has been only one revision (1 day old) and no recent changes.

**Root cause** (medium confidence, `resource_limits`): The container's last termination was OOMKilled (exit 137) and the Hub measured peak memory at 255Mi against a 256Mi limit, with a sizing requirement of about 307Mi. The deployment's only revision (revision 1, created 1d ago) has not changed, and the pod env includes LEAK_MIB_PER_MIN, which indicates the workload deliberately leaks memory, so it hits any fixed limit. The memory limit of 256Mi is too low for this workload's footprint. Confidence is medium because the previous container logs were empty, so the leak itself was not directly observed in logs.
**Severity:** high  ·  **Affected:** lab/Deployment/leaky, lab/Pod/leaky-8555f7bc7c-mtzbj

**Evidence**
- `kubernetes_describe_pod`: Container app: last_state terminated OOMKilled, exit_code 137; restarts 35; limits memory 256Mi, requests memory 128Mi; env includes LEAK_MIB_PER_MIN and MEMORY_MIB.
- `kubernetes_pod_logs`: Previous container logs returned no output, so no application error was captured.
- `sizing_for_workload`: kind/lab/Deployment/leaky: memory peak 255Mi against 256Mi limit; risk 'OOM-killed in 3 pods'; 'memory limit 256Mi is below the 307Mi it needs'; suggested memory_request 308Mi, memory_limit 308Mi.
- `kubernetes_describe_deployment`: Only rollout revision 1 (replicaset leaky-8555f7bc7c, created 1d ago, image python:3.12-alpine); Deployment Available and Progressing with NewReplicaSetAvailable.
- `kubernetes_recent_changes`: No rollouts or syncs in the last 180 minutes in namespace lab.

**Recommendations**
1. Raise the memory request and limit of deployment lab/leaky to about 308Mi each, per the Hub's suggestion, after getting approval for the change.
2. Confirm the leak is expected for this workload (LEAK_MIB_PER_MIN is set). If it is a real leak, the application needs a fix, because a higher limit only delays the OOM.
3. Check the pod's logs after the limit change to confirm the restarts stop and memory stabilises.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj", "previous": true}
3. `sizing_for_workload` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "lab", "name": "leaky"}
5. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 180}
6. `TriageReport` {"summary": "Pod leaky-8555f7bc7c-mtzbj is crash looping because its single container is repeatedly OOMKilled at its 256Mi memory limit (35 restarts). The workload is a leaking process, not a bad rollout: there has been only one revision (1 day old) and no recent changes.", "category": "resource_lim
