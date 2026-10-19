## Pod frontend-6f6b4986b9-hxdf2 is not ready because its nginx image tag 'nginx:1.99.99-does-not-exist' does not exist on Docker Hub, so the pod is stuck in ErrImagePull/ImagePullBackOff. The frontend deployment has only one revision, so no earlier working version exists. A separate checkout rollout 48s earlier removed DATABASE_URL and is crash-looping, which is outside this alert but needs attention.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment references a non-existent image tag (nginx:1.99.99-does-not-exist). The registry returns NotFound, so the container never starts and the pod never becomes ready. The deployment has only revision 1, so this was never a working image and there is no previous revision to fall back to. The tag was most likely a typo or was never pushed.
**Severity:** medium  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-6f6b4986b9-hxdf2

**Evidence**
- `kubernetes_describe_pod`: Container web is waiting with ErrImagePull; the message is 'docker.io/library/nginx:1.99.99-does-not-exist: not found'. Events show Back-off pulling image and ImagePullBackOff.
- `kubernetes_describe_deployment`: Deployment frontend has 0 of 1 replicas ready, Available=False (MinimumReplicasUnavailable). Rollout history has only revision 1, created 2m ago, with image nginx:1.99.99-does-not-exist.
- `kubernetes_list_pods`: frontend-6f6b4986b9-hxdf2 is Pending, 0/1 ready, age 2m, restarts 0.
- `kubernetes_recent_changes`: frontend revision 1 was created 2m ago. No earlier revision exists, so this is not a regression from a working version.
- `runbooks_runbook_for_alert`: The image-pull runbook says a manifest 'not found' error means the tag does not exist (typo or never pushed). The fix is to correct the tag or roll back.

**Recommendations**
1. Confirm the intended frontend image tag, for example with the team that owns the image, and check that it was pushed to the registry.
2. Update the frontend deployment to a valid nginx tag (e.g. a released version such as nginx:1.25 or whichever tag CI publishes). This is a config change that needs review and approval; do not apply it without sign-off.
3. Verify that the new pod becomes Ready and that the Deployment shows Available=True.
4. Separately, investigate the checkout deployment: revision 2 (48s ago) removed the DATABASE_URL env var from the app container, and its pods are crash-looping with exit code 1. Restoring DATABASE_URL is the likely fix.

Runbook: `image-pull`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_describe_pod`
3. `kubernetes_list_pods`
4. `kubernetes_recent_changes`
5. `kubernetes_describe_deployment`
