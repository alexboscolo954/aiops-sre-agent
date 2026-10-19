## Pod frontend-6f6b4986b9-hxdf2 is stuck in ErrImagePull because its only deployment revision uses the nonexistent image tag nginx:1.99.99-does-not-exist. The frontend deployment has 0 of 1 replicas ready and no earlier working revision to fall back to. Separately, a checkout rollout (revision 2) removed the DATABASE_URL env var, which is unrelated to this alert but needs a look.

**Root cause** (high confidence, `image_unavailable`): The frontend Deployment was created (revision 1, about 2 minutes before the alert) with the image tag nginx:1.99.99-does-not-exist. The registry returns NotFound, so the kubelet cannot pull the image and the pod stays in ErrImagePull/ImagePullBackOff and never becomes Ready. The tag was likely a typo or was never pushed. Because there is only one revision, there is no older ReplicaSet serving traffic, so the frontend is fully unavailable.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-6f6b4986b9-hxdf2

**Evidence**
- `kubernetes_describe_pod`: Pod frontend-6f6b4986b9-hxdf2 container web: waiting reason ErrImagePull, message 'failed to resolve reference docker.io/library/nginx:1.99.99-does-not-exist: not found'. Ready=False (ContainersNotReady). Events show Failed and BackOff with ImagePullBackOff.
- `kubernetes_describe_deployment`: frontend: replicas desired 1, ready 0. Available=False (MinimumReplicasUnavailable). rollout_history has only revision 1 (created 2m ago) with images [nginx:1.99.99-does-not-exist]. No prior working revision.
- `kubernetes_recent_changes`: frontend revision 1 created 2m ago with the bad image. checkout revision 2 rolled out 48s ago with env_removed app: [DATABASE_URL]. Not the cause of this alert.

**Recommendations**
1. Confirm the intended nginx tag with the owning team, then update the frontend deployment image to a tag that exists (for example, the last known good version). This is a config fix, not a rollback, since no earlier revision exists.
2. Check that the pod recovers to Ready after the image change, and that the readiness probe passes.
3. Add a CI check that verifies image tags exist in the registry before deploys.
4. Separately, review checkout revision 2, which removed the DATABASE_URL env var. If that was not intended, restore it, because it could break checkout at runtime.

Runbook: `deployment-unavailable`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_describe_pod`
3. `kubernetes_recent_changes`
4. `kubernetes_describe_deployment`
