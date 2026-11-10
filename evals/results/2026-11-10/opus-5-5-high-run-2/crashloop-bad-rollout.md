## The checkout pod checkout-869fc5bcc6-db5ps is crash looping (exit 1, 3 restarts). The app exits on startup with "FATAL: required env var DATABASE_URL is not set". Revision 2 of the checkout deployment, rolled out about 48s before, removed DATABASE_URL from the app container.

**Root cause** (high confidence, `bad_rollout`): Revision 2 of the checkout deployment (rolled out about 48s ago) removed the env var DATABASE_URL from the 'app' container (recent_changes diff: env_removed app: [DATABASE_URL]). The pod now runs with no env vars at all (describe_pod: env [], envFrom []). Checkout 1.4.0 needs DATABASE_URL to start, so it logs "FATAL: required env var DATABASE_URL is not set" and exits with code 1 every time. Revision 1 had the variable. The container was not OOMKilled (exit 1, memory limit 64Mi), so this is not a resource problem.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout

**Evidence**
- `kubernetes_list_pods`: checkout-869fc5bcc6-db5ps: Running 0/1 ready, 3 restarts, last terminated reason Error, exit code 1
- `kubernetes_pod_logs`: "checkout starting, version 1.4.0" then "FATAL: required env var DATABASE_URL is not set". The previous instance's logs were gone, so these are from the latest instance.
- `kubernetes_describe_pod`: Container app (python:3.12-alpine) has env: [] and env_from: []. State terminated Error exit 1, BackOff warning seen 4 times.
- `kubernetes_recent_changes`: checkout revision 2 rolled out 48s ago with diff env_removed {app: [DATABASE_URL]}. Revision 1 was created 2m ago.

**Recommendations**
1. Roll back checkout to revision 1 (kubectl -n demo rollout undo deployment/checkout --to-revision=1), or add DATABASE_URL back to the app container, taking its value from the proper Secret or ConfigMap.
2. Fix the source of revision 2 (manifest, Helm values or GitOps repo) so DATABASE_URL isn't dropped again on the next sync.
3. Check that the new pod starts and becomes Ready, and that the KubePodCrashLooping alert clears.
4. Don't restart the pod: a restart won't fix this crash loop.
5. Separately: other pods in demo are also failing for unrelated reasons. frontend is stuck in ErrImagePull on the tag nginx:1.99.99-does-not-exist, and reports is OOMKilled. Each needs its own triage.

Runbook: `pod-crashlooping`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
4. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true}
5. `kubernetes_recent_changes` {"cluster": "kind"}
6. `incidents_search` {"keywords": "checkout crash loop"}
