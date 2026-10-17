The latest rollout of `checkout` (revision 2, ReplicaSet `checkout-7c856f898c`) **dropped the `DATABASE_URL` env var**, and the new pod is crash-looping because of it.

- **Revision 1** (`checkout-7784c7f885`): image `python:3.12-alpine`, env `DATABASE_URL`. Its pod is Running 1/1 and logs "connected to database".
- **Revision 2** (`checkout-7c856f898c`): same image `python:3.12-alpine`, same resources, but **env is empty**. It has no `env_from` either. Its pod is 0/1 with 2 restarts, exit code 1 and BackOff events. Logs show `FATAL: required env var DATABASE_URL is not set`.

The image did not change. The only difference between the revisions is the missing `DATABASE_URL`.

**Impact:** the old revision-1 pod is still serving, so the deployment reports 1/1 available. The rollout is not completing, because the new pod never becomes ready.

**Recommended fix:** either roll back to revision 1 or restore `DATABASE_URL` in the deployment spec (value or Secret/ConfigMap reference). Per the pod-crashlooping runbook, a restart will not fix this.

**Evidence**
- `kubernetes_describe_deployment`: Revision 2 checkout-7c856f898c (created 36s ago): env [] and env_from []; revision 1 checkout-7784c7f885: env [DATABASE_URL]; image python:3.12-alpine in both.
- `kubernetes_list_pods`: checkout-7c856f898c-bjtfx 0/1, restarts 2, terminated Error exit code 1; checkout-7784c7f885-pwjtr 1/1 Running.
- `kubernetes_pod_logs`: New pod: "FATAL: required env var DATABASE_URL is not set". Old pod: "connected to database".
- `kubernetes_get_events`: Warning BackOff: restarting failed container app in pod checkout-7c856f898c-bjtfx.
- `runbooks_read_runbook`: pod-crashlooping: if a new revision caused it, roll back; if config is missing, fix the config; don't propose a restart.

**Tool calls**
1. `kubernetes_describe_deployment`
2. `kubernetes_list_pods`
3. `kubernetes_pod_logs`
4. `kubernetes_pod_logs`
5. `kubernetes_pod_logs`
6. `kubernetes_list_pods`
7. `kubernetes_pod_logs`
8. `runbooks_search_runbooks`
9. `runbooks_read_runbook`
10. `kubernetes_get_events`
