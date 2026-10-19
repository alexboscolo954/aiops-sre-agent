The latest rollout is revision 2 (ReplicaSet checkout-869fc5bcc6, created about 36s before the check). Compared with revision 1, the only config change is that the `DATABASE_URL` env var is gone: revision 1 set it, and revision 2 has an empty env list. The image is unchanged (python:3.12-alpine) and no env_from sources were added or removed. The rollout completed (Progressing=True, NewReplicaSetAvailable), but the deployment is not available: 0 of 1 desired replicas are ready, with reason MinimumReplicasUnavailable. The missing DATABASE_URL is a plausible cause, but I did not check pod logs or events, so I have not confirmed it. Next step: check the checkout pod logs and events to see why it is not ready. If the app needs DATABASE_URL, restoring it (for example by rolling back to revision 1) would be the likely fix.

**Evidence**
- `kubernetes_describe_deployment`: Rollout history: revision 2 (replicaset checkout-869fc5bcc6, created 36s ago) has env [] and env_from []; revision 1 (replicaset checkout-67d9799c78, created 2m ago, now 0 replicas) has env ["DATABASE_URL"]. Both use image python:3.12-alpine.
- `kubernetes_describe_deployment`: Deployment status: replicas desired 1, ready 0; Progressing=True (NewReplicaSetAvailable); Available=False (MinimumReplicasUnavailable, "Deployment does not have minimum availability.")

**Tool calls**
1. `kubernetes_describe_deployment`
