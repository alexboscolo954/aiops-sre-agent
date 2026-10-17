**The latest rollout (revision 2) removed the `DATABASE_URL` env var from the `app` container, and the new pod is now crashing because of it.** I looked in the `default` namespace of the `kind` cluster.

- **Revision 1** (ReplicaSet `checkout-7784c7f885`) had env `DATABASE_URL`.
- **Revision 2** (ReplicaSet `checkout-7c856f898c`, created about 36s ago) has no env vars and no `env_from`.
- Nothing else changed. The image is `python:3.12-alpine` in both revisions, and the memory limit and requests are the same in the current spec.

**Impact:**
- The revision 2 pod `checkout-7c856f898c-bjtfx` is 0/1 ready. It has restarted 2 times and last exited with Error (exit code 1).
- Its log says `checkout starting, version 1.4.0` and then `FATAL: required env var DATABASE_URL is not set`.
- The old revision 1 pod `checkout-7784c7f885-pwjtr` is still Running 1/1, so the rolling update is stalled and the deployment still looks Available.

**Recommendation:** restore `DATABASE_URL` in the deployment spec, using the same value or secret reference that revision 1 had. Alternatively, roll back to revision 1. I didn't compare the variable's value, because the tools don't return env var values.

**Evidence**
- `kubernetes_describe_deployment`: Revision 2 (checkout-7c856f898c) has env [] and env_from []. Revision 1 (checkout-7784c7f885) had env [DATABASE_URL]. The image is python:3.12-alpine in both.
- `kubernetes_list_pods`: checkout-7c856f898c-bjtfx is 0/1 ready with 2 restarts and terminated with Error (exit code 1). The old pod checkout-7784c7f885-pwjtr is Running 1/1.
- `kubernetes_pod_logs`: checkout starting, version 1.4.0 / FATAL: required env var DATABASE_URL is not set

**Tool calls**
1. `kubernetes_describe_deployment`
2. `kubernetes_list_deployments`
3. `kubernetes_list_pods`
4. `kubernetes_pod_logs`
5. `kubernetes_describe_deployment`
6. `kubernetes_describe_deployment`
7. `kubernetes_pod_logs`
8. `kubernetes_pod_logs`
