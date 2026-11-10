## The checkout pod in demo is crash looping because revision 2 of the checkout deployment removed the DATABASE_URL env var from the app container. The app exits at startup with "FATAL: required env var DATABASE_URL is not set". Per the Operator's teaching for this client, the fix is to restore DATABASE_URL from secret checkout-db and redeploy, not to roll back.

**Root cause** (high confidence, `bad_config`): Revision 2 of deployment checkout (ReplicaSet checkout-869fc5bcc6, created 36s before triage) dropped DATABASE_URL. Revision 1 (checkout-67d9799c78) had env DATABASE_URL; revision 2 has env: [] and env_from: []. The container logs show "FATAL: required env var DATABASE_URL is not set" followed by "checkout starting, version 1.4.0", so the app exits at startup with exit code 1 and Kubernetes backs off restarts (restarts: 3).
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_pod_logs`: Latest instance logs: "FATAL: required env var DATABASE_URL is not set" then "checkout starting, version 1.4.0".
- `kubernetes_describe_pod`: Container app: state terminated Error, exit_code 1, restarts 3, env: [] and env_from: []; Ready False (ContainersNotReady).
- `kubernetes_describe_deployment`: Revision 1 (checkout-67d9799c78) config app env: [DATABASE_URL]; revision 2 (checkout-869fc5bcc6, 36s old) config app env: []. Deployment Available False, MinimumReplicasUnavailable, ready 0 of 1.
- `kubernetes_recent_changes`: checkout revision 2 rollout: env_removed {app: [DATABASE_URL]}, 48s before triage.
- `runbooks_runbook_for_alert`: KubePodCrashLooping runbook: a new revision that broke a working one is a rollout fix, and missing config is fixed by restoring the config.

**Recommendations**
1. Do not roll back the checkout deployment for this missing DATABASE_URL crash loop (Operator teaching for this client).
2. Restore DATABASE_URL on the checkout deployment's app container from secret checkout-db (secretKeyRef), then redeploy. Confirm the secret and key exist first.
3. Verify the new pod reaches Ready and restarts stop. Check the logs for a clean startup past the DATABASE_URL check.
4. Find out why revision 2 dropped the env var (a Helm values or manifest change) so it does not recur.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true}
4. `kubernetes_recent_changes` {"cluster": "kind"}
5. `incidents_search` {"keywords": "checkout DATABASE_URL crashloop"}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
7. `TriageReport` {"summary": "The checkout pod in demo is crash looping because revision 2 of the checkout deployment removed the DATABASE_URL env var from the app container. The app exits at startup with \"FATAL: required env var DATABASE_URL is not set\". Per the Operator's teaching for this client, the fix is to 
