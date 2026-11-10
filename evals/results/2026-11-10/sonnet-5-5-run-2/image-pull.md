## Pod frontend-6f6b4986b9-hxdf2 is stuck in ErrImagePull because its image tag, nginx:1.99.99-does-not-exist, doesn't exist on Docker Hub. The pod never starts, so it can't become ready.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment, created at revision 1, references the image docker.io/library/nginx:1.99.99-does-not-exist. The registry returns NotFound for it, so the pull fails and the container stays in Waiting. This is a bad tag, not a registry outage or an auth problem. There is no earlier healthy revision, so frontend has never served traffic.
**Severity:** medium  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-6f6b4986b9-hxdf2

**Evidence**
- `kubernetes_list_pods`: frontend-6f6b4986b9-hxdf2 is Pending 0/1 with web in ErrImagePull: failed to resolve reference docker.io/library/nginx:1.99.99-does-not-exist: not found
- `kubernetes_recent_changes`: frontend was created at revision 1 about 2m ago, with no earlier revision to fall back to. The only other rollout is checkout revision 2, which removed the DATABASE_URL env var.

**Recommendations**
1. Set the frontend web container image to a valid nginx tag, for example a pinned stable 1.x tag, and redeploy. Fix it in the source manifest or GitOps repo, not only with a live edit.
2. Check that the new pod pulls the image and turns Ready.
3. Add a CI check that the image tag exists before it is deployed.
4. Separate issues in the same namespace: checkout is crash-looping (exit 1) after revision 2 removed DATABASE_URL, so restore that env var or roll back. reports is OOMKilled, so review its memory limit. Neither is the cause of this alert.

Runbook: `image-pull`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodNotReady"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "frontend"}
