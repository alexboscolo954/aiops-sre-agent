**The latest rollout (revision 2) removed the `DATABASE_URL` env var from checkout's `app` container, and the new pod is crash-looping because of it.**

- **Revision 1** (`checkout-7784c7f885`) ran `python:3.12-alpine` with env `DATABASE_URL`. Its pod is Running 1/1.
- **Revision 2** (`checkout-7c856f898c`, created about 5s after revision 1) uses the same image, `python:3.12-alpine`, with the same resources (32Mi memory request, 64Mi limit). Its env list is empty, so `DATABASE_URL` is gone.
- The revision 2 pod `checkout-7c856f898c-bjtfx` is 0/1 ready. It has restarted 2 times and exits with code 1 (Error). The previous container's logs show `checkout starting, version 1.4.0` followed by `FATAL: required env var DATABASE_URL is not set`.
- The old revision 1 pod is still serving, so the rolling update is stuck and checkout is still available.

**Recommendation:** Restore `DATABASE_URL` in the deployment spec, or roll back to revision 1 with `kubectl rollout undo`. Restarting the pod won't help, because the config is missing. The pod-crashlooping runbook says the same.

The `frontend` (bad image tag) and `reports` (OOMKilled) pods in this namespace are also unhealthy. They are separate problems and unrelated to this rollout.

**Evidence**
- `kubernetes_describe_deployment`: Revision 1 (checkout-7784c7f885) has env [DATABASE_URL]; revision 2 (checkout-7c856f898c) has env []. The image is python:3.12-alpine in both.
- `kubernetes_pod_logs`: Previous container logs of checkout-7c856f898c-bjtfx: 'checkout starting, version 1.4.0' then 'FATAL: required env var DATABASE_URL is not set'.
- `kubernetes_list_pods`: checkout-7c856f898c-bjtfx is 0/1 with 2 restarts and exit code 1 (Error). The old pod checkout-7784c7f885-pwjtr is 1/1 Running.
- `kubernetes_describe_pod`: The new pod has no env vars or envFrom, no probes, and a BackOff event 'Back-off restarting failed container app'.
- `runbooks_read_runbook`: pod-crashlooping: for missing config, fix the config; if a new revision caused it, roll back; don't propose a restart.

**Tool calls**
1. `kubernetes_describe_deployment`
2. `kubernetes_list_pods`
3. `kubernetes_pod_logs`
4. `kubernetes_get_events`
5. `runbooks_search_runbooks`
6. `runbooks_read_runbook`
7. `kubernetes_describe_deployment`
8. `kubernetes_describe_pod`
9. `kubernetes_list_pods`
10. `kubernetes_get_events`
