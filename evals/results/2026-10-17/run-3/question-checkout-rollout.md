**The latest checkout rollout (revision 2) removed the `DATABASE_URL` env var, and the new pod is crash-looping because of it.**

- Revision 1 (`checkout-7784c7f885`) had the env var `DATABASE_URL` on the `app` container.
- Revision 2 (`checkout-7c856f898c`) has no env vars and no `env_from`.
- The image is `python:3.12-alpine` in both revisions. Resource requests and limits are the same as far as the spec shows.
- The new pod `checkout-7c856f898c-bjtfx` is 0/1 ready with 2 restarts and exit code 1. Its log says `checkout starting, version 1.4.0` followed by `FATAL: required env var DATABASE_URL is not set`.
- The old revision 1 pod is still Running and ready, so checkout is still serving. The deployment shows 1/1 available and Progressing, but the rollout is not healthy.

**Recommended fix:** restore `DATABASE_URL` on the checkout deployment, for example from the revision 1 config, or run `kubectl rollout undo deployment/checkout`. I have no tools that change anything, so I haven't done either.

**Evidence**
- `kubernetes_describe_deployment`: Revision 1 (checkout-7784c7f885) env: [DATABASE_URL]; revision 2 (checkout-7c856f898c) env: [] and env_from: []; same image python:3.12-alpine
- `kubernetes_list_pods`: checkout-7c856f898c-bjtfx is 0/1 ready with 2 restarts and terminated Error (exit 1); the old pod checkout-7784c7f885-pwjtr is 1/1 Running
- `kubernetes_pod_logs`: checkout starting, version 1.4.0 / FATAL: required env var DATABASE_URL is not set
- `kubernetes_get_events`: BackOff: restarting failed container app in pod checkout-7c856f898c-bjtfx

**Tool calls**
1. `kubernetes_describe_deployment`
2. `kubernetes_list_deployments`
3. `kubernetes_list_pods`
4. `kubernetes_pod_logs`
5. `kubernetes_get_events`
