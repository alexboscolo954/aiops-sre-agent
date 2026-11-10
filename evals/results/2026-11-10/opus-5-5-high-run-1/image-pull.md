## The frontend pod frontend-6f6b4986b9-hxdf2 in demo can't start because its image tag nginx:1.99.99-does-not-exist doesn't exist on Docker Hub. It is stuck in ErrImagePull/ImagePullBackOff. This is revision 1 of the frontend deployment, so no earlier working version is serving traffic.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment was created about 2 minutes ago (revision 1) with container 'web' set to image nginx:1.99.99-does-not-exist. Docker Hub returns 'NotFound … docker.io/library/nginx:1.99.99-does-not-exist: not found', so the image can't be pulled and the pod stays Pending/ContainersNotReady. The tag looks like a typo or placeholder rather than a real nginx release. There is no earlier ReplicaSet to fall back on. The earlier FailedScheduling event (untolerated taint) has cleared: the pod was later assigned to squero-control-plane.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend

**Evidence**
- `kubernetes_list_pods`: frontend-6f6b4986b9-hxdf2 is Pending, 0/1 ready, container 'web' waiting with ErrImagePull: docker.io/library/nginx:1.99.99-does-not-exist: not found
- `kubernetes_describe_pod`: Image nginx:1.99.99-does-not-exist; events show 'Failed to pull image … rpc error: code = NotFound', 'Error: ErrImagePull' and 'Back-off pulling image', with Ready=False (ContainersNotReady)
- `kubernetes_recent_changes`: frontend deployment revision 1 was created 2m ago, with no earlier revision to roll back to

**Recommendations**
1. Change the frontend deployment's 'web' image to a real, approved nginx tag, e.g. `kubectl -n demo set image deployment/frontend web=nginx:<valid-tag>`, or fix the tag in the source manifest, Helm values or GitOps repo and redeploy.
2. Check whoever generated the manifest (CI or the release pipeline) to see why a tag that doesn't exist got deployed. Consider checking that an image exists before deploying.
3. Confirm the new pod pulls the image and becomes Ready with `kubectl -n demo get pods -l app=frontend`, and that the KubePodNotReady alert clears.
4. This is a separate issue in the same namespace: checkout has been crash looping since its revision 2 rollout, which removed DATABASE_URL, and reports is being OOMKilled. Triage both on their own.

Runbook: `image-pull`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodNotReady"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "frontend-6f6b4986b9-hxdf2"}
4. `incidents_search` {"keywords": "frontend"}
5. `kubernetes_recent_changes` {"cluster": "kind"}
