## Pod frontend-6f6b4986b9-hxdf2 is stuck Pending in ErrImagePull. Its image, docker.io/library/nginx:1.99.99-does-not-exist, does not exist in the registry.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment's only revision (revision 1, created about 2m ago) points at the nonexistent tag nginx:1.99.99-does-not-exist. The container runtime returns NotFound when it resolves that reference, so the container never starts and the pod never becomes Ready. This is a wrong tag, not a registry outage or an auth problem. I did not describe the pod or read its events.
**Severity:** medium  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-6f6b4986b9-hxdf2

**Evidence**
- `kubernetes_list_pods`: frontend-6f6b4986b9-hxdf2 is Pending, 0/1 ready, web container waiting in ErrImagePull: 'failed to resolve reference docker.io/library/nginx:1.99.99-does-not-exist: not found'
- `kubernetes_recent_changes`: frontend deployment was created (revision 1) about 2m ago. There is no earlier working revision, so no healthy replica is being served.

**Recommendations**
1. Set the frontend container image to a valid nginx tag, for example nginx:1.27 or whatever tag was intended, and fix the source manifest or Helm values so it isn't reverted.
2. Confirm the new pod pulls the image and turns Ready, using kubernetes_list_pods.
3. Add a CI check that the image tag exists before deploying.

Runbook: `image-pull`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodNotReady"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `incidents_search` {"keywords": "frontend"}
