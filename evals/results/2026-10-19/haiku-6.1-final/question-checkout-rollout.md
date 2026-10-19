The checkout deployment's latest rollout is revision 2, about 48 seconds before this check. Its only recorded change was removing the environment variable DATABASE_URL from the app container. Revision 1 (created about 2 minutes earlier) had no recorded diff. I did not check pod health or logs, so I can't yet say whether removing DATABASE_URL has broken anything.

**Evidence**
- `kubernetes_recent_changes`: demo/checkout revision 2, change 'rollout', 48s ago, diff: env_removed {"app": ["DATABASE_URL"]}
- `kubernetes_recent_changes`: demo/checkout revision 1, change 'created', 2m ago, diff: {}

**Tool calls**
1. `kubernetes_recent_changes`
