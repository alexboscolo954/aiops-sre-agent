## frontend pod frontend-6f6b4986b9-hxdf2 is not ready because it is stuck in ImagePullBackOff. Its image tag nginx:1.99.99-does-not-exist does not exist on Docker Hub.

**Root cause** (high confidence, `image_unavailable`): The frontend Deployment (revision 1, created about 2m ago) points to the image nginx:1.99.99-does-not-exist. Docker Hub answers the pull with 'NotFound ... not found', so the container never starts and the pod stays Pending/ContainersNotReady. There is no earlier working revision to fall back to. The separate checkout rollout, which removed DATABASE_URL, is unrelated to this pod.
**Severity:** medium  ·  **Affected:** demo/Deployment/frontend

**Evidence**
- `kubernetes_describe_pod`: container web, image nginx:1.99.99-does-not-exist, is waiting in ErrImagePull/ImagePullBackOff: 'docker.io/library/nginx:1.99.99-does-not-exist: not found'
- `kubernetes_recent_changes`: frontend has only revision 1, created 2m ago. There is no prior revision to roll back to.

**Recommendations**
1. Change the frontend Deployment's image to a valid nginx tag, for example the one your manifests pin such as nginx:1.27, and apply it through the normal deploy pipeline.
2. Watch the rollout and confirm the new pod reaches Ready.
3. Add a CI check that the image tag exists before a deploy goes out.
4. Look into the checkout rollout that removed DATABASE_URL separately; it may cause its own alert.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "frontend-6f6b4986b9-hxdf2"}
2. `kubernetes_recent_changes` {"cluster": "kind"}
3. `incidents_search` {"keywords": "frontend"}
