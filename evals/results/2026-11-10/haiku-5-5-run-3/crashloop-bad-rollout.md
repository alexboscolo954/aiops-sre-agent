## Pod checkout-869fc5bcc6-db5ps is crash looping because revision 2 of the checkout deployment removed the DATABASE_URL env var from the app container. The app exits at startup with "FATAL: required env var DATABASE_URL is not set". Rolling back to revision 1 (which had DATABASE_URL) should fix it.

**Root cause** (high confidence, `bad_rollout`): Revision 2 of deployment checkout (ReplicaSet checkout-869fc5bcc6, created about 36s before triage) has env: [] and env_from: []. Revision 1 (ReplicaSet checkout-67d9799c78) had env DATABASE_URL. The diff shows env_removed app: [DATABASE_URL]. The container's previous log is "FATAL: required env var DATABASE_URL is not set" and then the process exits with code 1. The image and version (1.4.0) are unchanged, so the rollout's config change is the cause. The memory limit (64Mi) is not involved: the termination reason is Error, not OOMKilled.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_describe_pod`: Container app: state terminated Error, exit_code 1, restarts 3; env list is empty; Ready=False ContainersNotReady; BackOff events.
- `kubernetes_pod_logs`: Previous log: 'FATAL: required env var DATABASE_URL is not set' followed by 'checkout starting, version 1.4.0'.
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago with diff env_removed {app: [DATABASE_URL]}.
- `kubernetes_describe_deployment`: Revision 1 (checkout-67d9799c78) config env: [DATABASE_URL], replicas 0; revision 2 (checkout-869fc5bcc6) config env: [], replicas 1, ready 0; Available=False MinimumReplicasUnavailable.

**Recommendations**
1. Roll back the checkout deployment to revision 1 (kubectl rollout undo deployment/checkout -n demo), which restores DATABASE_URL. This needs approval.
2. Alternatively, restore the DATABASE_URL env var (from a Secret or ConfigMap as used in revision 1) in the checkout deployment spec, then check that the new pod stays Ready.
3. Find out why revision 2 dropped DATABASE_URL (likely a Helm values or manifest change) so the next rollout doesn't repeat it.
4. Confirm the checkout deployment shows Available=True and that the pod's restart count stops increasing.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
6. `incidents_search` {"keywords": "checkout DATABASE_URL crashloop"}
7. `TriageReport` {"summary": "Pod checkout-869fc5bcc6-db5ps is crash looping because revision 2 of the checkout deployment removed the DATABASE_URL env var from the app container. The app exits at startup with \"FATAL: required env var DATABASE_URL is not set\". Rolling back to revision 1 (which had DATABASE_URL) sh
8. `TriageReport` {"summary": "Pod checkout-869fc5bcc6-db5ps is crash looping because revision 2 of the checkout deployment removed the DATABASE_URL env var from the app container. The app exits at startup with \"FATAL: required env var DATABASE_URL is not set\". Rolling back to revision 1 (which had DATABASE_URL) sh
