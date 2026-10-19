The latest rollout (revision 2, ReplicaSet checkout-869fc5bcc6, about 36-48s old) removed the DATABASE_URL environment variable from the app container. Revision 1 set env DATABASE_URL; revision 2 has no env vars. The image did not change (python:3.12-alpine in both revisions), and resource requests and limits were not part of the reported diff. Since that rollout the deployment reports 0 of 1 replicas ready and Available=False (MinimumReplicasUnavailable), so the missing variable is a likely suspect for the outage, though I did not check pod logs to confirm it. Restoring DATABASE_URL (for example by rolling back to revision 1) would be the fix to consider.

**Evidence**
- `kubernetes_describe_deployment`: checkout rollout_history: revision 2 (replicaset checkout-869fc5bcc6, created 36s ago) config app env: [] ; revision 1 (checkout-67d9799c78, created 2m ago) config app env: ["DATABASE_URL"]; both use image python:3.12-alpine.
- `kubernetes_describe_deployment`: checkout replicas desired 1, ready 0; conditions Available=False reason MinimumReplicasUnavailable, Progressing=True reason NewReplicaSetAvailable.
- `kubernetes_recent_changes`: demo/checkout revision 2 change 'rollout' when 48s, diff: env_removed {"app": ["DATABASE_URL"]}.

**Tool calls**
1. `kubernetes_describe_deployment`
2. `kubernetes_recent_changes`
