## The checkout pod is crash looping because revision 2 of the checkout deployment removed the DATABASE_URL env var from the app container. The app exits at startup with "FATAL: required env var DATABASE_URL is not set". Revision 1 had DATABASE_URL, so this is a bad rollout that dropped config.

**Root cause** (high confidence, `bad_rollout`): Checkout revision 2 (ReplicaSet checkout-869fc5bcc6, created about 36-48s before triage) removed DATABASE_URL from the app container. Revision 1 (checkout-67d9799c78) had DATABASE_URL in its env; revision 2 has env: [] and env_from: []. The app logs "FATAL: required env var DATABASE_URL is not set" and exits with code 1 (Error), with restarts=3. The image (python:3.12-alpine) and resource limits are unchanged, so the missing env var is the cause.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_pod_logs`: Previous logs were gone; latest instance shows "FATAL: required env var DATABASE_URL is not set" followed by "checkout starting, version 1.4.0".
- `kubernetes_describe_pod`: checkout-869fc5bcc6-db5ps container app: state terminated Error, exit_code 1, restarts 3, env [] and env_from [], Ready False (ContainersNotReady), BackOff events.
- `kubernetes_recent_changes`: demo/checkout revision 2 rollout 48s ago: env_removed {app: [DATABASE_URL]}. Revision 1 was created 2m ago.
- `kubernetes_describe_deployment`: rollout_history revision 1 (checkout-67d9799c78) config app env: [DATABASE_URL]; revision 2 (checkout-869fc5bcc6) config app env: []. Deployment Available=False, MinimumReplicasUnavailable, replicas ready 0 of 1.

**Recommendations**
1. Do not roll back the checkout deployment for this crash loop, per the Operator's teaching for this client.
2. Restore DATABASE_URL on the checkout deployment's app container from secret checkout-db (for example, a secretKeyRef or envFrom for that secret, matching the key used in revision 1), then redeploy so a new revision starts.
3. Verify the new pod reaches Ready and the checkout deployment shows Available=True, and that the restart count stops increasing.
4. Check why the revision 2 manifest dropped DATABASE_URL (for example, a Helm values or GitOps change) so it does not recur.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
3. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "container": null, "tail_lines": 100, "previous": true}
4. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
5. `incidents_search` {"keywords": "checkout DATABASE_URL crashloop", "days": 90, "limit": 5}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
