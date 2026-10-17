**The latest rollout (revision 2) dropped the `DATABASE_URL` env var from the checkout container, and the new pod is crash-looping because of it.**

- **Revision 1** (`checkout-7784c7f885`) uses `python:3.12-alpine` and sets env `DATABASE_URL`.
- **Revision 2** (`checkout-7c856f898c`, created about 5s after rev 1) uses the same image, `python:3.12-alpine`. Its env list is empty and there is no `envFrom`. The only change shown is that `DATABASE_URL` was removed. Requests and limits are the same in the container spec I saw (memory limit 64Mi). I didn't compare them against rev 1 directly.

**Impact:**
- The rev 2 pod `checkout-7c856f898c-bjtfx` is 0/1 ready with 2 restarts. It exits with code 1 and is in BackOff. Its log says `FATAL: required env var DATABASE_URL is not set`.
- The old rev 1 pod `checkout-7784c7f885-pwjtr` is still Running 1/1 and logged `connected to database`. It is still serving, so the deployment reports Available. The rollout is stuck and can't finish.

**Recommendation:** Restore `DATABASE_URL` in the deployment spec, either by restoring it from the rev 1 config or by rolling back to revision 1. Per the pod-crashlooping runbook, a restart will not fix this.

The same-namespace `frontend` (bad image tag `nginx:1.99.99-does-not-exist`) and `reports` (OOMKilled) are failing for unrelated reasons.

**Evidence**
- `kubernetes_describe_deployment`: Rev 2 checkout-7c856f898c (36s old) has env [] and no env_from. Rev 1 checkout-7784c7f885 (41s old) has env [DATABASE_URL]. Both use image python:3.12-alpine.
- `kubernetes_pod_logs`: The rev 2 pod checkout-7c856f898c-bjtfx logs 'checkout starting, version 1.4.0 / FATAL: required env var DATABASE_URL is not set'. The previous run's log is the same.
- `kubernetes_list_pods`: checkout-7c856f898c-bjtfx is 0/1 with 2 restarts and terminated with Error exit code 1. The old pod checkout-7784c7f885-pwjtr is 1/1 Running with 0 restarts.
- `kubernetes_pod_logs`: The rev 1 pod logs 'connected to database'.
- `kubernetes_get_events`: Warning BackOff: Back-off restarting failed container app in pod checkout-7c856f898c-bjtfx.
- `runbooks_read_runbook`: The pod-crashlooping runbook says missing config after a new revision is fixed by restoring the config or rolling back, and that a restart does not fix a crash loop.

**Tool calls**
1. `kubernetes_list_deployments`
2. `kubernetes_list_deployments`
3. `kubernetes_describe_deployment`
4. `kubernetes_list_pods`
5. `kubernetes_pod_logs`
6. `kubernetes_pod_logs`
7. `runbooks_runbook_for_alert`
8. `runbooks_read_runbook`
9. `kubernetes_describe_deployment`
10. `kubernetes_list_pods`
11. `kubernetes_pod_logs`
12. `runbooks_read_runbook`
13. `kubernetes_get_events`
14. `kubernetes_get_events`
