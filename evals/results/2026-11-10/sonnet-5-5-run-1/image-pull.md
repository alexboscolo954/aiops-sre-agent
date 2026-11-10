## Pod frontend-6f6b4986b9-hxdf2 is stuck Pending in ErrImagePull. The image tag docker.io/library/nginx:1.99.99-does-not-exist doesn't exist in the registry, so the container never starts.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment references the nonexistent image tag nginx:1.99.99-does-not-exist. The registry returns NotFound when the node tries to pull it. The deployment was created at revision 1 with this tag, so there was no earlier working revision and the pod has never become ready.
**Severity:** medium  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-6f6b4986b9-hxdf2

**Evidence**
- `kubernetes_list_pods`: frontend-6f6b4986b9-hxdf2 is Pending 0/1 with web in ErrImagePull: failed to resolve reference docker.io/library/nginx:1.99.99-does-not-exist: not found
- `kubernetes_recent_changes`: frontend was only created (revision 1) about 2m ago, with no later rollout and no earlier working revision to fall back to
- `runbooks_runbook_for_alert`: The image-pull runbook says a NotFound / manifest unknown error means the tag doesn't exist, and the fix is to correct the tag.

**Recommendations**
1. Change the frontend deployment image to a valid nginx tag (for example a current stable 1.x release), either with kubectl set image or in the source manifest/GitOps repo.
2. Confirm the new pod pulls the image and becomes Ready, then check that the alert clears.
3. Add a CI or admission check that verifies the image tag exists before deploy.
4. Separate from this alert: demo/checkout is crash-looping after revision 2 removed the DATABASE_URL env var. demo/reports is being OOMKilled. Triage both separately.

Runbook: `image-pull`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodNotReady"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "frontend"}
