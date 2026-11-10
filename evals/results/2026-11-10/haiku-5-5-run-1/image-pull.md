## frontend pod frontend-6f6b4986b9-hxdf2 is not ready because its only container image tag `nginx:1.99.99-does-not-exist` does not exist in the registry, so the pod is stuck in ErrImagePull/ImagePullBackOff.

**Root cause** (high confidence, `image_unavailable`): The frontend Deployment's only revision references image tag `nginx:1.99.99-does-not-exist`, which the registry reports as not found.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend

**Evidence**
- `kubernetes_describe_pod`: Container web image nginx:1.99.99-does-not-exist, waiting ErrImagePull: failed to resolve reference ... not found

**Recommendations**
1. Set a valid frontend image tag (needs approval).

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodNotReady"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "frontend"}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "frontend-6f6b4986b9-hxdf2"}
6. `runbooks_read_runbook` {"name": "image-pull"}
7. `incidents_search` {"keywords": "frontend nginx image pull"}
8. `TriageReport` {"summary": "frontend pod frontend-6f6b4986b9-hxdf2 is not ready because its only container image tag `nginx:1.99.99-does-not-exist` does not exist in Docker Hub, so the pod is stuck in ErrImagePull/ImagePullBackOff. The deployment has 0 of 1 replicas ready. This is the sole revision (revision 1, cr
9. `TriageReport` {"summary": "frontend pod frontend-6f6b4986b9-hxdf2 is not ready because its only container image tag `nginx:1.99.99-does-not-exist` does not exist in Docker Hub, so the pod is stuck in ErrImagePull/ImagePullBackOff. The deployment has 0 of 1 replicas ready. This is the sole revision (revision 1, cr
10. `TriageReport` {"summary": "frontend pod frontend-6f6b4986b9-hxdf2 is not ready because its only container image tag `nginx:1.99.99-does-not-exist` does not exist in Docker Hub, so the pod is stuck in ErrImagePull/ImagePullBackOff. The deployment has 0 of 1 replicas ready. This is the sole revision (revision 1, cr
11. `TriageReport` {"summary": "frontend pod frontend-6f6b4986b9-hxdf2 is not ready because its only container image tag `nginx:1.99.99-does-not-exist` does not exist in the registry, so the pod is stuck in ErrImagePull/ImagePullBackOff. The deployment has 0 of 1 replicas ready. This is the sole revision (revision 1, 
12. `TriageReport` {"summary": "frontend pod frontend-6f6b4986b9-hxdf2 is not ready because its only container image tag `nginx:1.99.99-does-not-exist` does not exist in the registry, so the pod is stuck in ErrImagePull/ImagePullBackOff. The deployment has 0 of 1 replicas ready. This is the sole revision (revision 1, 
13. `TriageReport` {"summary": "frontend pod frontend-6f6b4986b9-hxdf2 is not ready because its only container image tag `nginx:1.99.99-does-not-exist` does not exist in the registry, so the pod is stuck in ErrImagePull/ImagePullBackOff. The deployment has 0 of 1 replicas ready. This is the sole revision (revision 1, 
14. `TriageReport` {"summary": "frontend pod frontend-6f6b4986b9-hxdf2 is not ready because its only container image tag `nginx:1.99.99-does-not-exist` does not exist in the registry, so the pod is stuck in ErrImagePull/ImagePullBackOff. The deployment has 0 of 1 replicas ready.", "category": "image_unavailable", "pro
15. `TriageReport` {"summary": "frontend pod frontend-6f6b4986b9-hxdf2 is not ready because its only container image tag `nginx:1.99.99-does-not-exist` does not exist in the registry, so the pod is stuck in ErrImagePull/ImagePullBackOff. The deployment has 0 of 1 replicas ready.", "category": "image_unavailable", "pro
16. `TriageReport` {"summary": "frontend pod frontend-6f6b4986b9-hxdf2 is not ready because its only container image tag `nginx:1.99.99-does-not-exist` does not exist in the registry, so the pod is stuck in ErrImagePull/ImagePullBackOff.", "category": "image_unavailable", "probable_root_cause": "The frontend Deploymen
