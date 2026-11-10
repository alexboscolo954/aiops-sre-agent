## Pod checkout-869fc5bcc6-db5ps is crash looping because revision 2 of the checkout deployment removed the DATABASE_URL env var from the app container. The app exits at startup with 'FATAL: required env var DATABASE_URL is not set' (exit code 1).

**Root cause** (high confidence, `bad_rollout`): Revision 2 of deployment checkout (ReplicaSet checkout-869fc5bcc6, created about 36s before triage) removed env DATABASE_URL from container app. Revision 1 (checkout-67d9799c78) had env [DATABASE_URL] and is now scaled to 0. The current pod's container terminates with exit code 1 and reason Error, and the previous-instance logs show 'FATAL: required env var DATABASE_URL is not set'. The app fails fast at startup without the variable, so the pod restarts repeatedly (restarts: 3, BackOff event). The image python:3.12-alpine and resource limits are unchanged between revisions.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_pod_logs`: Previous/latest instance log: 'FATAL: required env var DATABASE_URL is not set' followed by 'checkout starting, version 1.4.0'.
- `kubernetes_describe_pod`: Container app state terminated Error, exit_code 1, restarts 3; Ready False (ContainersNotReady); BackOff event 'Back-off restarting failed container app'; container env list is empty.
- `kubernetes_describe_deployment`: rollout_history: revision 2 (replicaset checkout-869fc5bcc6, 36s old) config app env [] vs revision 1 (checkout-67d9799c78, 2m old) config app env [DATABASE_URL]; Available False, MinimumReplicasUnavailable, ready 0 of desired 1.
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago with diff env_removed {app: [DATABASE_URL]}.

**Recommendations**
1. Roll back checkout to revision 1 (kubectl rollout undo deployment/checkout -n demo --to-revision=1), or re-add the DATABASE_URL env var from its original source (Secret or ConfigMap) to the checkout deployment.
2. Confirm the pod reaches Running and Ready, and that the KubePodCrashLooping alert clears.
3. Review the change that dropped DATABASE_URL from revision 2 (likely a manifest or Helm values change) so it is not reapplied; add a CI check for required env vars.
4. Restarting the pod will not help, since the config is missing.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "container": "app", "tail_lines": 50, "previous": true}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
6. `incidents_search` {"keywords": "checkout crashloop DATABASE_URL", "days": 90, "limit": 5}
