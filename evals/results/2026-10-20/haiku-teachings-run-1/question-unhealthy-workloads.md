Three workloads in namespace demo are unhealthy, all at 0/1 ready, each for a different reason:

1. **frontend** (Pending, ErrImagePull): the image `nginx:1.99.99-does-not-exist` does not exist on Docker Hub, so the pull fails with NotFound and the pod is stuck in ImagePullBackOff. Fix: set the image to a valid tag and roll out again.

2. **checkout** (CrashLoopBackOff, 3 restarts, exit code 1): the app exits at startup with `FATAL: required env var DATABASE_URL is not set`. The deployment's env does not provide DATABASE_URL. Fix: add the variable (for example from a Secret or ConfigMap) to the checkout deployment.

3. **reports** (CrashLoopBackOff, 3 restarts, OOMKilled, exit 137): the container has a 48Mi memory limit and is killed by the kernel. Fix: raise the memory limit, or check whether the workload's memory use has grown.

An older checkout ReplicaSet pod (checkout-67d9799c78-n6mfv) also logged a FailedScheduling event (node taint). It is not in the current pod list, so it is probably a leftover from an earlier revision and does not affect current health.

I did not check recent rollouts or past incidents, so I cannot say which change introduced each problem.

**Evidence**
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps Running 0/1, restarts 3, last terminated Error exit 1; frontend-6f6b4986b9-hxdf2 Pending 0/1, waiting ErrImagePull; reports-55b4fffc66-hmq7f Running 0/1, restarts 3, last terminated OOMKilled exit 137.
- `kubernetes_list_deployments`: checkout, frontend and reports all 0/1 ready with MinimumReplicasUnavailable; frontend image is nginx:1.99.99-does-not-exist.
- `kubernetes_get_events`: frontend events: Failed to pull image "nginx:1.99.99-does-not-exist": ... not found; BackOff restarting failed container app for checkout and reports pods.
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps app log: 'FATAL: required env var DATABASE_URL is not set' followed by 'checkout starting, version 1.4.0'.
- `kubernetes_describe_pod`: reports-55b4fffc66-hmq7f container app: limits memory 48Mi, requests memory 32Mi, state terminated OOMKilled exit 137, restarts 3, env empty.

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": ""}
2. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_get_events` {"cluster": "kind", "namespace": "demo", "warnings_only": true}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "container": "app", "tail_lines": 50, "previous": false}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "reports-55b4fffc66-hmq7f"}
6. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": ""}
