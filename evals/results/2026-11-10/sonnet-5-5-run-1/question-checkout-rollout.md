**The latest rollout (revision 2, about 48s ago) removed the `DATABASE_URL` env var from the `app` container, and checkout is now crash-looping because of it.**

- **What changed:** Revision 1 (`checkout-67d9799c78`) had `DATABASE_URL` set. Revision 2 (`checkout-869fc5bcc6`) has no env vars. The image is the same in both (`python:3.12-alpine`), and so are the resources (requests 10m CPU and 32Mi memory, memory limit 64Mi). Nothing else changed.
- **Effect:** The deployment is 0/1 ready, with `Available=False` (`MinimumReplicasUnavailable`). Pod `checkout-869fc5bcc6-db5ps` has exited with `Error` (exit 1) and restarted 3 times. It is in BackOff. The pod logs say `FATAL: required env var DATABASE_URL is not set`.
- **Recommendation:** Restore `DATABASE_URL` on the deployment, for example by rolling back to revision 1 or re-adding the var from its original source. This matches the pod-crashlooping runbook, which says a bad revision calls for a rollback or a config fix. A restart won't help.
- **Past incidents:** I found no past Reports for checkout.
- **Other deployments:** `frontend` (image `nginx:1.99.99-does-not-exist` can't be pulled) and `reports` (OOMKilled) are also unhealthy, but for unrelated reasons.

**Evidence**
- `kubernetes_recent_changes`: demo/checkout revision 2 rolled out 48s ago with diff env_removed: app: [DATABASE_URL]. Revision 1 was the initial creation.
- `kubernetes_describe_deployment`: Revision 2 (checkout-869fc5bcc6) has env [] and image python:3.12-alpine. Revision 1 (checkout-67d9799c78) had env [DATABASE_URL] with the same image. Deployment is 0/1 ready, Available=False.
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps logs: 'FATAL: required env var DATABASE_URL is not set'.
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps is 0/1 ready with 3 restarts and last termination Error, exit code 1.
- `runbooks_read_runbook`: pod-crashlooping runbook: missing config or a bad new revision is the usual cause. Fix by rolling back the revision or fixing the config, and don't propose a restart.

**Tool calls**
1. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
2. `kubernetes_recent_changes` {"cluster": "kind"}
3. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": "app=checkout"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "tail_lines": 20}
5. `runbooks_search_runbooks` {"keywords": "checkout crashloop env"}
6. `runbooks_read_runbook` {"name": "pod-crashlooping"}
7. `incidents_search` {"keywords": "checkout DATABASE_URL"}
8. `read_more` {"result_id": "none"}
9. `runbooks_read_runbook` {"name": "deployment-unavailable"}
10. `incidents_search` {"keywords": "checkout"}
11. `kubernetes_get_events` {"cluster": "kind", "namespace": "demo"}
12. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
13. `incidents_search` {"keywords": "DATABASE_URL missing env crash"}
14. `read_more` {"result_id": "x"}
15. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
16. `incidents_search` {"keywords": "rollback"}
17. `kubernetes_list_deployments` {"cluster": "kind", "namespace": "demo"}
18. `read_more` {"result_id": "y"}
