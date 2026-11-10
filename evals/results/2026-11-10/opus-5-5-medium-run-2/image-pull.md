## The frontend pod frontend-6f6b4986b9-hxdf2 can't start because its image nginx:1.99.99-does-not-exist doesn't exist on Docker Hub, so the pull fails with ErrImagePull. Frontend has 0 of 1 replicas ready. This deployment has only one revision, so no older ReplicaSet is left serving traffic.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment (revision 1, ReplicaSet frontend-6f6b4986b9, created about 2 minutes before the check) points at image tag nginx:1.99.99-does-not-exist. The registry returns 'docker.io/library/nginx:1.99.99-does-not-exist: not found', so the container never starts and the pod stays Pending/ErrImagePull. Because there's only one revision, there is no earlier working version to roll back to: the tag itself is wrong.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend

**Evidence**
- `kubernetes_list_pods`: frontend-6f6b4986b9-hxdf2 is Pending, 0/1 ready, with container web waiting on ErrImagePull: 'failed to resolve reference "docker.io/library/nginx:1.99.99-does-not-exist": not found'
- `kubernetes_describe_deployment`: frontend has desired 1, ready 0, Available=False (MinimumReplicasUnavailable). Its only rollout revision is 1 (frontend-6f6b4986b9, created 2m ago) with image nginx:1.99.99-does-not-exist
- `runbooks_runbook_for_alert`: The image-pull runbook says 'not found' means the tag doesn't exist (a typo, or CI never pushed it). The fix is to correct the tag or roll back.

**Recommendations**
1. Change the frontend deployment's web container image to a tag that exists (for example a released nginx version such as nginx:1.27), or to whatever tag was meant, and redeploy through the normal pipeline or GitOps source.
2. Check that the new pod pulls the image and becomes Ready, so the deployment shows 1/1 available.
3. Find where the bad tag came from (manifest typo or a CI push that never happened). Consider adding image tag validation in CI before deploying.
4. Other pods in demo are unhealthy too and need their own triage: checkout is crash-looping with exit code 1, and reports is crash-looping with OOMKilled. They are separate from this alert.

Runbook: `image-pull`

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
2. `runbooks_runbook_for_alert` {"alertname": "KubePodNotReady"}
3. `incidents_search` {"keywords": "frontend"}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "frontend"}
