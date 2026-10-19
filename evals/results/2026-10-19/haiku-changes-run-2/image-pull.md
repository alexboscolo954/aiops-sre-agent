## frontend-6f6b4986b9-hxdf2 is not ready because its only container image, nginx:1.99.99-does-not-exist, does not exist on Docker Hub, so the kubelet cannot pull it (ErrImagePull/ImagePullBackOff). The frontend deployment has zero ready replicas, and this is its first and only revision, created about 2 minutes ago. A separate checkout rollout (revision 2, DATABASE_URL removed) is crash-looping, but it is not the cause of this alert.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment was created with a non-existent image tag, nginx:1.99.99-does-not-exist. The registry returns NotFound, so the pod never starts. There is no earlier working revision to roll back to, so the frontend has no running pods at all.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-6f6b4986b9-hxdf2

**Evidence**
- `kubernetes_describe_pod`: Container web uses image nginx:1.99.99-does-not-exist; state Waiting with ErrImagePull; message 'failed to resolve reference ... not found'. Ready=False (ContainersNotReady).
- `kubernetes_get_events`: Repeated Warning Failed events: 'Failed to pull image "nginx:1.99.99-does-not-exist" ... not found' followed by Error: ImagePullBackOff.
- `kubernetes_describe_deployment`: replicas desired=1 ready=0; Available=False (MinimumReplicasUnavailable); rollout_history has only revision 1 (frontend-6f6b4986b9, created 2m ago) with the bad image.
- `kubernetes_recent_changes`: frontend revision 1 'created' 2m ago, the only frontend change in the window. The other recent change is checkout revision 2 (env DATABASE_URL removed), which is unrelated to the frontend image.
- `runbooks_runbook_for_alert`: KubePodNotReady maps to deployment-unavailable. Its guidance points to the image-pull runbook for ErrImagePull/ImagePullBackOff, which says a bad tag is the usual cause.

**Recommendations**
1. Confirm the intended frontend image tag with the owning team, for example by checking the CI pipeline or the image registry for the tag that exists.
2. Update the frontend deployment to a valid tag, such as nginx with a real version, and watch the rollout until the pod is Ready.
3. Fixing the tag is the only change needed for frontend. Scaling or restarting the pod will not help while the tag is missing.
4. Separately, investigate the checkout deployment (revision 2 removed DATABASE_URL from env, and its container 'app' is crash-looping). Consider rolling checkout back to revision 1 or restoring DATABASE_URL.
5. Note that reports pods are also crash-looping, so check them as well.

Runbook: `deployment-unavailable`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_describe_pod`
3. `kubernetes_get_events`
4. `kubernetes_describe_deployment`
5. `kubernetes_recent_changes`
