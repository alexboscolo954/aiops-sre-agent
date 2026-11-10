## checkout in demo is crash looping (exit 1, 3 restarts). Revision 2 of the deployment, rolled out 48s ago, removed the DATABASE_URL env var, and the app now quits at startup with 'FATAL: required env var DATABASE_URL is not set'.

**Root cause** (high confidence, `bad_rollout`): Revision 2 of deployment demo/checkout went out about 48s before this check. Its only change was removing the env var DATABASE_URL from container 'app'. Version 1.4.0 of the app needs that variable, so it logs 'FATAL: required env var DATABASE_URL is not set' and exits with code 1. The pod spec now has no env vars and no envFrom sources. Revision 1, created about 2m ago, had the variable. It was replaced so soon that this is inferred from the diff, not seen working. This is not memory: the container ends in Error/exit 1, not OOMKilled/137.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout

**Evidence**
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'checkout starting, version 1.4.0' then 'FATAL: required env var DATABASE_URL is not set'. Previous logs were gone, so these are the latest run's logs.
- `kubernetes_recent_changes`: demo/checkout revision 2 rolled out 48s ago with diff env_removed: {app: [DATABASE_URL]}; revision 1 was created 2m ago
- `kubernetes_describe_pod`: Container 'app' (python:3.12-alpine) is terminated Error with exit code 1 and 3 restarts, with BackOff events; env is [] and env_from is []; memory limit 64Mi, no OOM
- `runbooks_runbook_for_alert`: pod-crashlooping runbook: exit 1 plus missing config, or a new revision that caused it, means fix the config or roll back; a restart does not fix a crash loop

**Recommendations**
1. Roll back demo/checkout to revision 1 (kubectl rollout undo deployment/checkout -n demo --to-revision=1), or put DATABASE_URL back in the 'app' container's env from its Secret or config source.
2. Watch the new pods start and confirm 'FATAL: required env var DATABASE_URL is not set' no longer shows in the logs and the pods become Ready.
3. Ask whoever made revision 2 why DATABASE_URL was removed. Add a check to CI or the manifests so required env vars can't be dropped.
4. Don't restart the pod: it will keep crashing until the config is fixed.

Runbook: `pod-crashlooping`

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 50}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "checkout crashloop"}
5. `runbooks_runbook_for_alert` {"alertname": "KubePodCrashLooping"}
