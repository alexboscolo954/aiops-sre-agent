## checkout pod is crash looping, exiting with code 1 and the log line 'FATAL: required env var DATABASE_URL is not set'. The checkout rollout to revision 2, about 48s ago, removed DATABASE_URL from the app container.

**Root cause** (high confidence, `bad_rollout`): Revision 2 of deployment demo/checkout (rolled out about 48s ago) removed the DATABASE_URL env var from container 'app'. The pod now has no env vars at all (env: []). On startup checkout 1.4.0 checks for this variable, finds it missing and exits with code 1. It has restarted 3 times and is in BackOff.
**Severity:** high  ·  **Affected:** demo/Deployment/checkout

**Evidence**
- `kubernetes_pod_logs`: checkout-869fc5bcc6-db5ps: 'FATAL: required env var DATABASE_URL is not set' after 'checkout starting, version 1.4.0'. The previous run's logs were gone, so this is the latest run.
- `kubernetes_recent_changes`: checkout revision 2 rollout 48s ago: env_removed app: [DATABASE_URL]
- `kubernetes_describe_pod`: Container app has env: [], is terminated with Error exit_code 1, has 3 restarts and BackOff events

**Recommendations**
1. Roll back checkout to revision 1 (kubectl rollout undo deployment/checkout -n demo), or add DATABASE_URL back to the deployment spec.
2. Check that the new pods become Ready and that the logs no longer show the FATAL error.
3. Find out why DATABASE_URL was dropped in the change source (manifest or Helm values) so the next deploy doesn't remove it again.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps"}
2. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "checkout-869fc5bcc6-db5ps", "previous": true, "tail_lines": 50}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "checkout crashloop"}
