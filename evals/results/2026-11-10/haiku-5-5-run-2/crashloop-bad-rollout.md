## Pod checkout-869fc5bcc6-db5ps is crash looping because revision 2 of the checkout deployment removed the DATABASE_URL env var from container "app". The app exits at startup with "FATAL: required env var DATABASE_URL is not set". Rolling back to revision 1 (which had DATABASE_URL) or restoring the variable should fix it.

**Root cause** (high confidence, `bad_rollout`): Revision 2 of deployment checkout (ReplicaSet checkout-869fc5bcc6, created ~36s before triage) removed DATABASE_URL from the app container. Revision 1 (checkout-67d9799c78) had DATABASE_URL in its env and is now scaled to 0. The container logs show the app fails fast on startup without it, and the restart count is climbing (restarts: 3, exit code 1, Error).
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_pod_logs`: Previous/latest instance log: 'FATAL: required env var DATABASE_URL is not set' followed by 'checkout starting, version 1.4.0'
- `kubernetes_describe_pod`: Container app: state terminated Error, exit_code 1, restarts 3, env list empty; Ready False (ContainersNotReady); BackOff events for container app
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago with diff env_removed app: [DATABASE_URL]
- `kubernetes_describe_deployment`: Revision 1 (checkout-67d9799c78) config env: [DATABASE_URL], replicas 0; revision 2 (checkout-869fc5bcc6) env: [], Available False MinimumReplicasUnavailable
- `runbooks_runbook_for_alert`: pod-crashlooping runbook: a new revision that removed config is the cause; fix is rollback of that revision or restore the config

**Recommendations**
1. Roll back deployment checkout to revision 1 (`kubectl rollout undo deployment/checkout -n demo --to-revision=1`), which carries DATABASE_URL. This needs human approval.
2. Alternatively, re-add the DATABASE_URL env var (from its original source Secret/ConfigMap) to the checkout deployment's app container, if revision 1 is not the desired state.
3. Confirm the checkout pod becomes Ready and the crash loop stops; check the DATABASE_URL source is still valid for the new version 1.4.0.
4. Find out why DATABASE_URL was removed in revision 2 (the change may be from a Helm values or GitOps manifest) so it is not reintroduced.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
6. `incidents_search` {"keywords": "checkout DATABASE_URL crashloop"}
7. `TriageReport` {"summary": "Pod checkout-869fc5bcc6-db5ps is crash looping because revision 2 of the checkout deployment removed the DATABASE_URL env var from container \"app\". The app exits at startup with \"FATAL: required env var DATABASE_URL is not set\". Rolling back to revision 1 (which had DATABASE_URL) or
