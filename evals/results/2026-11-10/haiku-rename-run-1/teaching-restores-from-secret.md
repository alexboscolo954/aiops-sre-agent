## The checkout pod is crash looping because revision 2 of the checkout deployment removed the DATABASE_URL env var from the app container, so the app exits at startup with "FATAL: required env var DATABASE_URL is not set". Per Operator guidance, the fix is to restore DATABASE_URL from secret checkout-db and redeploy, not roll back. Two other pods in demo are also failing, but they are separate problems.

**Root cause** (high confidence, `bad_config`): Checkout revision 2 (replicaset checkout-869fc5bcc6, created about 36s before triage) changed the app container's env from [DATABASE_URL] in revision 1 to [] in revision 2. The app logs "FATAL: required env var DATABASE_URL is not set" and exits with code 1 (Error), which triggers the crash loop (3 restarts, 0/1 ready). Revision 1 (replicaset checkout-67d9799c78) had DATABASE_URL and is now scaled to 0. The image and resources are unchanged, so the env removal is the deciding change.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout, demo/Pod/checkout-869fc5bcc6-db5ps

**Evidence**
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps app container, previous instance: "FATAL: required env var DATABASE_URL is not set" followed by "checkout starting, version 1.4.0"; last terminated Error, exit code 1.
- `kubernetes_recent_changes`: demo checkout revision 2 rollout 48s ago with diff env_removed app: [DATABASE_URL]; revision 1 was created 2m ago.
- `kubernetes_describe_deployment`: checkout: desired 1, ready 0; revision 2 config app env [] env_from []; revision 1 config app env [DATABASE_URL]; Available=False (MinimumReplicasUnavailable).
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps: ready 0/1, restarts 3, last_terminated Error exit 1 at 22s.

**Recommendations**
1. Do not roll back the checkout deployment. Instead, restore the DATABASE_URL env var on the app container from secret checkout-db (for example, env valueFrom secretKeyRef, or envFrom that includes the secret's DATABASE_URL key). Confirm the secret and key exist first.
2. Redeploy checkout with that change (this needs human approval as it is a change action) and confirm the new pod reaches 1/1 Ready with no further restarts.
3. Check the checkout app logs after the redeploy to confirm the database connection succeeds.
4. Separately, investigate demo/reports-55b4fffc66-hmq7f, which is OOMKilled (exit 137, memory limit 64Mi per its deployment) and needs a limit review or leak check per the oom-killed runbook.
5. Separately, fix demo/frontend-6f6b4986b9-hxdf2, which is in ErrImagePull because the image tag nginx:1.99.99-does-not-exist does not exist. Correct the tag to a valid one.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": ""}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "container": "app", "tail_lines": 30, "previous": true}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "checkout"}
6. `incidents_search` {"keywords": "checkout DATABASE_URL crashloop", "days": 90, "limit": 5}
