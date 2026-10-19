## Pod checkout-869fc5bcc6-db5ps is crash looping because checkout revision 2 (rolled out about 48s before the alert) removed the DATABASE_URL env var, and the app exits at startup with 'FATAL: required env var DATABASE_URL is not set'. Revision 1 had the variable, so rolling back fixes it. The same namespace also has a reports pod in OOMKilled loops and a frontend pod with a bad image tag, which are separate issues.

**Root cause** (high confidence, `bad_rollout`): checkout revision 2 dropped the DATABASE_URL env var from container 'app' (revision 1 set it). On startup the app checks for DATABASE_URL, logs the FATAL error and exits with code 1, so the pod crash loops and the deployment has 0 ready replicas.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_pod_logs`: previous/latest instance log: 'FATAL: required env var DATABASE_URL is not set' followed by 'checkout starting, version 1.4.0'
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps: ready 0/1, restarts 3, last terminated Error exit code 1
- `kubernetes_recent_changes`: demo/checkout revision 2 rollout 48s ago, diff env_removed app: [DATABASE_URL]
- `kubernetes_describe_deployment`: checkout rollout history: revision 2 (current) env: [] ; revision 1 (replicaset checkout-67d9799c78, scaled to 0) env: [DATABASE_URL]; Available=False MinimumReplicasUnavailable
- `kubernetes_list_pods`: Also in namespace demo: reports-55b4fffc66-hmq7f restarts 3, last terminated OOMKilled exit 137 (limit on checkout is 64Mi; reports limits not checked)
- `kubernetes_list_pods`: Also in namespace demo: frontend-6f6b4986b9-hxdf2 Pending, ErrImagePull for nginx:1.99.99-does-not-exist (not crash looping)

**Recommendations**
1. Roll back demo/checkout to revision 1 (the one with DATABASE_URL), e.g. kubectl rollout undo deployment/checkout -n demo --to-revision=1, or restore the DATABASE_URL env (from the same Secret/ConfigMap source) in revision 2. This needs human approval since it changes the cluster.
2. Confirm checkout pod becomes Ready and restarts stop. Then add a check in the chart/CI that required env vars are present in the rendered Deployment.
3. Separately investigate demo/reports OOMKilled: describe the pod for its memory limit, compare with memory working_set in Prometheus, then raise the limit or fix the leak (oom-killed runbook). Not verified in this triage.
4. Separately fix demo/frontend image tag nginx:1.99.99-does-not-exist to a valid tag.
5. Caveat: the checkout pod's previous logs were gone, so the FATAL line comes from the latest instance; it is consistent with the exit code 1 and the env diff, but the previous instance was not read directly.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_recent_changes`
4. `kubernetes_pod_logs`
5. `kubernetes_describe_deployment`
