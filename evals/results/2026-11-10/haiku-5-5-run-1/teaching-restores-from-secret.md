## checkout pod checkout-869fc5bcc6-db5ps is crash looping with exit 1 because DATABASE_URL is missing. Revision 2 of the checkout deployment removed DATABASE_URL from the app container's env, and revision 1 had it. Per the Operator's teaching for this client, do not roll back; restore DATABASE_URL from secret checkout-db and redeploy.

**Root cause** (high confidence, `bad_config`): Revision 2 of deployment checkout (ReplicaSet checkout-869fc5bcc6, created about 36s before triage) removed the env var DATABASE_URL from container "app". Revision 1 (checkout-67d9799c78) had DATABASE_URL in its env. The current pod's log shows "FATAL: required env var DATABASE_URL is not set" followed by "checkout starting, version 1.4.0", and the container exits with Error (exit 1), so the app fails at startup on the missing config.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps: Running, ready 0/1, restarts 3, last terminated Error exit code 1.
- `kubernetes_pod_logs`: Latest instance logs: 'FATAL: required env var DATABASE_URL is not set' then 'checkout starting, version 1.4.0'.
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago: diff env_removed app: [DATABASE_URL]. Revision 1 created 2m ago with no diff.
- `kubernetes_describe_deployment`: Revision 2 (checkout-869fc5bcc6) config app env: [] and env_from: []. Revision 1 (checkout-67d9799c78) config app env: [DATABASE_URL]. Deployment Available=False, MinimumReplicasUnavailable.
- `runbooks_runbook_for_alert`: KubePodCrashLooping maps to the pod-crashlooping runbook: Error exit points to config checks and to rollout history.

**Recommendations**
1. Do not roll back the checkout deployment. Per the Operator's teaching for this client, restore DATABASE_URL instead.
2. Re-add DATABASE_URL to the app container of deployment checkout, sourced from secret checkout-db (secretKeyRef), then redeploy. Human approval is needed for this change.
3. Confirm the pod reaches Ready 1/1 and the restart count stops increasing.
4. Find out why revision 2 dropped DATABASE_URL (a manifest or Helm values change) so the next rollout keeps it.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "checkout"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
7. `runbooks_read_runbook` {"name": "pod-crashlooping"}
8. `TriageReport` {"summary": "checkout pod checkout-869fc5bcc6-db5ps is crash looping with exit 1 because DATABASE_URL is missing. Revision 2 of the checkout deployment removed DATABASE_URL from the app container's env, and revision 1 had it. Per the Operator's teaching for this client, do not roll back; restore DAT
9. `TriageReport` {"summary": "checkout pod checkout-869fc5bcc6-db5ps is crash looping with exit 1 because DATABASE_URL is missing. Revision 2 of the checkout deployment removed DATABASE_URL from the app container's env, and revision 1 had it. Per the Operator's teaching for this client, do not roll back; restore DAT
