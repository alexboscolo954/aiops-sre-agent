## frontend pod frontend-6f6b4986b9-hxdf2 never becomes ready. It is stuck in ImagePullBackOff because the image tag nginx:1.99.99-does-not-exist is not on Docker Hub.

**Root cause** (high confidence, `image_unavailable`): The frontend Deployment, created as revision 1 about 2 minutes ago, points to image nginx:1.99.99-does-not-exist. The registry says it does not exist: 'docker.io/library/nginx:1.99.99-does-not-exist: not found'. So the web container can never start. There is no earlier working revision to roll back to.
**Severity:** medium  ·  **Affected:** demo/Deployment/frontend

**Evidence**
- `kubernetes_describe_pod`: Container web, image nginx:1.99.99-does-not-exist, is waiting in ErrImagePull/ImagePullBackOff. The pull fails with 'NotFound ... not found'.
- `kubernetes_recent_changes`: frontend revision 1 was created 2m ago and has had no later rollouts. The only other change is checkout revision 2, which removed DATABASE_URL and has nothing to do with this pod.

**Recommendations**
1. Change the frontend Deployment's image to a tag that exists, such as a published nginx 1.x release, e.g. kubectl -n demo set image deploy/frontend web=nginx:<valid-tag>.
2. Find and fix the image tag in the source manifest or GitOps repo so the next sync doesn't put the bad tag back.
3. Separately, look into the checkout rollout to revision 2, which removed DATABASE_URL. It may cause its own alert.

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "frontend-6f6b4986b9-hxdf2"}
2. `kubernetes_recent_changes` {"cluster": "kind"}
3. `incidents_search` {"keywords": "frontend"}
