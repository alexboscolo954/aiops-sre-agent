## The alerted pod frontend-6f6b4986b9-hxdf2 is stuck in Pending with ErrImagePull because its image tag nginx:1.99.99-does-not-exist does not exist in the registry. The frontend deployment was created about 2 minutes ago with only revision 1, so there is no earlier working revision and the frontend has no ready replicas. Two other pods in the namespace, checkout and reports, are also not ready, but for different reasons.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment references a non-existent image tag (docker.io/library/nginx:1.99.99-does-not-exist). The registry returns 'not found', so the kubelet cannot pull the image and the pod never starts. The tag looks like a typo or a version that CI never pushed.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-6f6b4986b9-hxdf2

**Evidence**
- `kubernetes_list_pods`: frontend-6f6b4986b9-hxdf2 is Pending, 0/1 ready, container 'web' waiting with ErrImagePull. Message: 'failed to resolve reference docker.io/library/nginx:1.99.99-does-not-exist: not found'.
- `kubernetes_recent_changes`: frontend revision 1 was 'created' about 2m ago with no diff. This is the only revision, so no earlier working ReplicaSet exists to fall back on.
- `runbooks_runbook_for_alert`: The image-pull runbook says a 'not found' message means the tag does not exist (typo or CI never pushed it), and recommends fixing the tag or rolling back.

**Recommendations**
1. Confirm the intended frontend image tag with the team that owns the frontend manifest, or check the CI registry for the tag that should exist.
2. Update the frontend deployment to a tag that exists, e.g. kubectl -n demo set image deployment/frontend web=<valid-image>. Verify the new pod becomes Ready. This is a change, so it needs human approval first.
3. Do not scale the deployment as a fix. Scaling does not help when the image cannot be pulled.
4. Separately investigate the other unhealthy pods in demo. checkout (revision 2, DATABASE_URL was removed from the app container in a rollout 48s ago, pod in Error with exit code 1) is most likely a bad_rollout and needs DATABASE_URL restored or the rollout reverted. reports is OOMKilled (exit 137) and may need a memory limit increase.

Runbook: `image-pull`

**Tool calls**
1. `kubernetes_list_pods`
2. `kubernetes_recent_changes`
3. `runbooks_runbook_for_alert`
