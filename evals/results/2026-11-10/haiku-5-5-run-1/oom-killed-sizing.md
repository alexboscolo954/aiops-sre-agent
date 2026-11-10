## Pod leaky-8555f7bc7c-mtzbj is crash looping because its single container is repeatedly OOMKilled at the 256Mi memory limit (35 restarts). The workload is a steady-state memory leaker, not a recent change: there has been no rollout in the last 180 minutes and the deployment has only revision 1, one day old.

**Root cause** (high confidence, `resource_limits`): The app container's memory limit (256Mi) is below what the workload needs (Hub sizing peak 255Mi, needs about 307Mi). Last termination reason is OOMKilled with exit code 137, and the Sizing reports it OOM-killed in 3 pods. The container runs a leak (env LEAK_MIB_PER_MIN), so it climbs to the limit and is killed, then restarts. Memory request 128Mi is also below the 256Mi it needs. The rollout history shows only revision 1 (created 1d ago) and recent_changes lists no rollouts, so this is not caused by a new revision.
**Severity:** high  ·  **Affected:** lab/Deployment/leaky

**Evidence**
- `kubernetes_describe_pod`: Container app: last_state terminated OOMKilled, exit_code 137, restarts 35; limits memory 256Mi, requests memory 128Mi; pod currently Running and Ready.
- `kubernetes_pod_logs`: Previous container logs returned no output, so the crash is not visible in logs; OOMKilled status is the evidence.
- `sizing_for_workload`: Deployment leaky, container app: memory peak 255Mi against 256Mi limit; risk 'OOM-killed in 3 pods'; 'memory limit 256Mi is below the 307Mi it needs'; suggested memory_request 308Mi, memory_limit 308Mi.
- `kubernetes_describe_deployment`: Rollout history has only revision 1 (ReplicaSet leaky-8555f7bc7c, created 1d ago); image python:3.12-alpine; deployment Available.
- `kubernetes_recent_changes`: No rollouts or changes in the last 180 minutes across the lab namespace.

**Recommendations**
1. Raise the memory limit and request of deployment leaky's app container to about 308Mi each (Hub suggestion), via a reviewed change to the deployment manifest.
2. Confirm that the leak is intended (env LEAK_MIB_PER_MIN, MEMORY_MIB, PROFILE are set in the container). If it is a test workload, the alternative is to stop the leak rather than size for it.
3. Watch restarts after the change; the pod should stop being OOMKilled. A leak will still grow over time, so plan a fix for the app if it is not a test workload.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj", "previous": true}
3. `sizing_for_workload` {"cluster": "kind", "namespace": "lab", "name": "leaky-8555f7bc7c-mtzbj"}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "lab", "name": "leaky"}
5. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 180}
6. `TriageReport` {"summary": "Pod leaky-8555f7bc7c-mtzbj is crash looping because its single container is repeatedly OOMKilled at the 256Mi memory limit (35 restarts). The workload is a steady-state memory leaker, not a recent change: there has been no rollout in the last 180 minutes and the deployment has only revi
