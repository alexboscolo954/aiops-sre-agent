## checkout pod crash loops (exit 1) because revision 2, rolled out 48s ago, removed the DATABASE_URL env var. The app exits on startup with 'FATAL: required env var DATABASE_URL is not set'.

**Root cause** (high confidence, `bad_rollout`): checkout revision 2 (48s ago) removed DATABASE_URL from container 'app'. Revision 1 had it. checkout 1.4.0 needs this variable and exits with code 1 when it is missing, so the pod has restarted 3 times and is in BackOff.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout

**Evidence**
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'FATAL: required env var DATABASE_URL is not set' (previous logs were gone, so this is the latest run)
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago: env_removed app: [DATABASE_URL]
- `kubernetes_describe_pod`: Container app terminated with Error, exit code 1, 3 restarts, BackOff event, pod env list is empty

**Recommendations**
1. Roll back checkout to revision 1 (kubectl rollout undo deployment/checkout -n demo), or put DATABASE_URL back into the deployment spec.
2. Check that the new pods become Ready and stop restarting.
3. Find out why DATABASE_URL was removed in the source manifest, so the next deploy doesn't bring the problem back.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 50}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "checkout crashloop"}
