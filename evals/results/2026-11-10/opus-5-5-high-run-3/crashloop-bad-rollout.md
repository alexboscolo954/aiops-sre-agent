## checkout crash loops on startup with exit 1 because revision 2 of the checkout deployment, rolled out about 48s ago, removed the DATABASE_URL env var. The app exits with 'FATAL: required env var DATABASE_URL is not set'.

**Root cause** (high confidence, `bad_rollout`): Revision 2 of deployment demo/checkout, rolled out about 48s ago, removed DATABASE_URL from container 'app' (diff env_removed: app: [DATABASE_URL]). checkout 1.4.0 needs that variable at startup. It logs 'FATAL: required env var DATABASE_URL is not set' and exits with code 1. The pod now has no env vars and no envFrom sources, so it has restarted 3 times and is in BackOff. Revision 1 still had the variable. I didn't check directly that revision 1 ran cleanly.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout

**Evidence**
- `kubernetes_recent_changes`: demo/checkout revision 2 rolled out 48s ago with diff env_removed {app: [DATABASE_URL]}; revision 1 was created 2m ago
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'checkout starting, version 1.4.0' then 'FATAL: required env var DATABASE_URL is not set'. The previous run's logs were gone, so this is the latest run.
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps is Running but 0/1 ready, 3 restarts, last terminated Error with exit code 1
- `kubernetes_describe_pod`: Container app (python:3.12-alpine) has env: [] and env_from: []; Warning BackOff 'Back-off restarting failed container app'

**Recommendations**
1. Roll back checkout to revision 1 (kubectl rollout undo deployment/checkout -n demo --to-revision=1), or add DATABASE_URL back to the deployment, from its Secret or ConfigMap source.
2. Confirm the new pod becomes Ready and no longer logs the FATAL error.
3. Find out why the change that removed DATABASE_URL went out, and fix it in the source manifests or Helm values so the next sync doesn't remove it again.
4. Don't restart the pod: a restart won't fix this crash loop.
5. These are separate problems in the same namespace: frontend is stuck on ErrImagePull (the tag nginx:1.99.99-does-not-exist doesn't exist), and reports keeps getting OOMKilled. Triage them separately.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true}
5. `kubernetes_recent_changes` {"cluster": "kind"}
6. `incidents_search` {"keywords": "checkout crashloop"}
