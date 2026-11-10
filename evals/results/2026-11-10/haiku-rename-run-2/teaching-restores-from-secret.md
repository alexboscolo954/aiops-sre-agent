## Checkout pod checkout-869fc5bcc6-db5ps is crash looping because revision 2 of the checkout deployment removed the DATABASE_URL env var from the app container. The app exits at startup with 'FATAL: required env var DATABASE_URL is not set'. Two other demo workloads are also unhealthy but are not the subject of this alert: frontend has an ErrImagePull and reports is OOMKilled.

**Root cause** (high confidence, `bad_rollout`): Checkout revision 2 (ReplicaSet checkout-869fc5bcc6, created about 36s before triage) removed DATABASE_URL from the app container's env, while revision 1 (checkout-67d9799c78) had it. Revision 2's config shows env: [] and env_from: []. The new pod logs show 'FATAL: required env var DATABASE_URL is not set' followed by the startup banner, and it exits with code 1 (Error), with 3 restarts in about 35s. The deployment shows Available=False (MinimumReplicasUnavailable), 0 of 1 ready. The fix is to restore DATABASE_URL from secret checkout-db and redeploy. Do not roll back the deployment, per the Operator's instruction for this client.
**Severity:** high  ·  **Affected:** demo/deployment/checkout, demo/pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps app container, previous logs: 'FATAL: required env var DATABASE_URL is not set' then 'checkout starting, version 1.4.0'
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps: ready 0/1, restarts 3, last terminated Error exit code 1, age 35s
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago with diff env_removed: app: [DATABASE_URL]
- `kubernetes_describe_deployment`: checkout rollout_history: revision 2 config env [] and env_from []; revision 1 config env [DATABASE_URL]; Available=False, MinimumReplicasUnavailable

**Recommendations**
1. Restore the DATABASE_URL env var on the checkout deployment's app container, sourced from secret checkout-db (secretKeyRef), so the config matches revision 1. Confirm the key name in secret checkout-db first. This is a change, so it needs Operator approval.
2. Once the change is applied, confirm the new checkout pod is Running and ready, and that restarts stop.
3. Do not roll back the checkout deployment to revision 1 (Operator instruction for this client).
4. Separately, frontend-6f6b4986b9-hxdf2 is in ErrImagePull because image nginx:1.99.99-does-not-exist was not found. Fix the image tag. This is outside this alert.
5. Separately, reports-55b4fffc66-hmq7f is OOMKilled (exit 137) with a 2m age. Follow the oom-killed runbook. This is outside this alert.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": ""}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `incidents_search` {"keywords": "checkout crash loop", "days": 90, "limit": 5}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "container": "app", "tail_lines": 20, "previous": true}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
