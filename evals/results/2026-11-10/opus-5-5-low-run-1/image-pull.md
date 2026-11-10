## The frontend pod frontend-6f6b4986b9-hxdf2 in the demo namespace can't start. Its image tag nginx:1.99.99-does-not-exist doesn't exist on Docker Hub, so the pull fails (ErrImagePull, then ImagePullBackOff).

**Root cause** (high confidence, `image_unavailable`): The frontend deployment (revision 1, created about 2 minutes ago) points its web container at nginx:1.99.99-does-not-exist. The registry returns NotFound: "docker.io/library/nginx:1.99.99-does-not-exist: not found". With no image, the container never starts and the pod stays not ready. This deployment has no earlier revision that worked. A FailedScheduling event for a node taint came first, but the pod was scheduled after that, so the taint isn't what's blocking it now.
**Severity:** medium  ·  **Affected:** demo/Deployment/frontend

**Evidence**
- `kubernetes_describe_pod`: Container web, image nginx:1.99.99-does-not-exist, is waiting in ErrImagePull with 'failed to resolve reference ... not found'. Events also show ImagePullBackOff.
- `kubernetes_recent_changes`: The frontend deployment was created at revision 1 about 2 minutes ago and has had no later rollouts.

**Recommendations**
1. Change the frontend deployment's image to an nginx tag that exists (for example nginx:1.27), using kubectl set image deployment/frontend web=nginx:1.27 -n demo or the change in your source of truth.
2. Watch the rollout finish and check that the pod becomes Ready.
3. Add a CI check that confirms an image tag exists before it gets deployed.
4. Separately, checkout revision 2 removed the DATABASE_URL env var. This alert didn't cover checkout, so check its health on its own.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "frontend-6f6b4986b9-hxdf2"}
2. `kubernetes_recent_changes` {"cluster": "kind"}
3. `incidents_search` {"keywords": "frontend"}
