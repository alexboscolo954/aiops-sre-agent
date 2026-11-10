## checkout pod crash loops (exit 1) because revision 2, rolled out 48s ago, removed the DATABASE_URL env var. The app exits on startup with 'FATAL: required env var DATABASE_URL is not set'.

**Root cause** (high confidence, `bad_rollout`): Revision 2 of deployment demo/checkout removed DATABASE_URL from container 'app'. Checkout v1.4.0 needs this variable and exits with code 1 at startup without it. The pod now has no env vars at all and has restarted 3 times.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout

**Evidence**
- `kubernetes_recent_changes`: checkout revision 2 rolled out 48s ago with diff env_removed: app: [DATABASE_URL]
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'FATAL: required env var DATABASE_URL is not set' after 'checkout starting, version 1.4.0'
- `kubernetes_describe_pod`: Container app terminated with Error, exit code 1, 3 restarts, BackOff events; env list is empty

**Recommendations**
1. Roll back: kubectl rollout undo deployment/checkout -n demo (back to revision 1, which still sets DATABASE_URL)
2. Or put DATABASE_URL back in the deployment spec and re-apply it
3. Find out why the variable was removed in revision 2, and add a check that required env vars are present before deploy

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 50}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "checkout crashloop"}
