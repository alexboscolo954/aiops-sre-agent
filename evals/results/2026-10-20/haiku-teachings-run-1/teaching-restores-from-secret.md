## The checkout pod is crash looping because revision 2 of the checkout deployment, rolled out about 48 seconds before the alert, removed the DATABASE_URL env var. The app exits with status 1 at startup because the variable is missing. The fix is to restore DATABASE_URL from secret checkout-db and redeploy, not to roll back.

**Root cause** (high confidence, `bad_rollout`): Revision 2 of deployment checkout (ReplicaSet checkout-869fc5bcc6, created 36s before describe) has an empty env list for container app, while revision 1 (checkout-67d9799c78) had DATABASE_URL. The recent-changes diff reports env_removed for app: [DATABASE_URL]. The container logs show 'FATAL: required env var DATABASE_URL is not set' and the pod's last state is Error with exit code 1 and restarts=3. The app exits on startup, so the pod never becomes Ready and the deployment has Available=False (MinimumReplicasUnavailable, 0 of 1 ready).
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_pod_logs`: Latest instance logs: 'FATAL: required env var DATABASE_URL is not set' followed by 'checkout starting, version 1.4.0'. Previous-instance logs were already gone.
- `kubernetes_describe_pod`: Container app: state terminated Error, exit_code 1, last_state exit_code 1, restarts 3; env list is empty and env_from is empty; Ready=False (ContainersNotReady); BackOff event 'Back-off restarting failed container app'.
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago with diff env_removed {app: [DATABASE_URL]}; revision 1 created 2m ago with no diff.
- `kubernetes_describe_deployment`: rollout_history: revision 2 (checkout-869fc5bcc6) config app env [] and env_from []; revision 1 (checkout-67d9799c78) config app env [DATABASE_URL]; Available=False, MinimumReplicasUnavailable; replicas desired 1, ready 0.
- `incidents_search`: No past Report in the last 90 days matches checkout crashloop, so there is no prior fix to compare against.

**Recommendations**
1. Do not roll back the checkout deployment for this crash loop. The Operator's teaching for this client says to restore DATABASE_URL from secret checkout-db and redeploy instead.
2. Confirm that secret checkout-db exists in namespace demo and contains the key used for the database URL. The read-only tools could not check this.
3. Re-add DATABASE_URL to the checkout deployment's app container, sourced from secret checkout-db (secretKeyRef), then redeploy. This is a changing action and needs human approval before it runs.
4. After the rollout, confirm the new pod reaches Ready and the checkout deployment shows Available=True, and that the KubePodCrashLooping alert clears.
5. Ask the team that made revision 2 why DATABASE_URL was dropped, so the change is not repeated by a later deploy.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "container": null, "tail_lines": 100, "previous": true}
5. `incidents_search` {"keywords": "checkout crashloop", "days": 90, "limit": 5}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
