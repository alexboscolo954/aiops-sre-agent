## Pod frontend-6f6b4986b9-hxdf2 is not ready because its only container image, nginx:1.99.99-does-not-exist, does not exist in the registry, so the kubelet is stuck in ErrImagePull/ImagePullBackOff. The frontend deployment has only one revision, so there is no earlier working revision to roll back to. Two other demo pods (checkout and reports) are also unhealthy, but they are separate problems.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment's single revision (revision 1, created about 2m ago) uses image tag nginx:1.99.99-does-not-exist. The registry returns 'not found' for docker.io/library/nginx:1.99.99-does-not-exist, so the pod never starts. The pod is Pending with 0/1 ready and restarts 0. The tag is almost certainly a typo or a version that was never published. Because this is the first revision, no prior image is known to work. The runbook's image-pull guidance (tag does not exist) matches exactly.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-6f6b4986b9-hxdf2

**Evidence**
- `kubernetes_describe_pod`: Pod frontend-6f6b4986b9-hxdf2 is Pending, container web is waiting with ErrImagePull, and the message is 'failed to resolve reference docker.io/library/nginx:1.99.99-does-not-exist: not found'. Events show ImagePullBackOff with count 2.
- `kubernetes_describe_deployment`: Deployment frontend has desired 1 and ready 0. Available is False (MinimumReplicasUnavailable). rollout_history has only revision 1 (replicaset frontend-6f6b4986b9, created 2m ago) with images [nginx:1.99.99-does-not-exist].
- `kubernetes_list_pods`: frontend-6f6b4986b9-hxdf2 is Pending, 0/1 ready, restarts 0, age 2m, with ErrImagePull as the waiting reason.
- `kubernetes_recent_changes`: frontend revision 1 was 'created' 2m ago with no diff, so there is no earlier revision that changed the image. The image was wrong from the first deploy.
- `runbooks_runbook_for_alert`: Alert KubePodNotReady maps to the deployment-unavailable runbook. Its image-pull runbook says a tag that is 'not found' is a typo or a tag CI never pushed, and that the fix is to correct the tag or roll back.

**Recommendations**
1. Find the correct nginx tag that exists (check the CI pipeline or the image registry) and update the frontend deployment's container image to it. Replace the placeholder '1.99.99-does-not-exist' with a published tag such as a known-good nginx version.
2. Confirm the new pod reaches Ready with kubectl get pods -n demo -l app=frontend, or check the readiness with kubernetes_list_pods.
3. Because there is no earlier working revision, rollback will not help. Do not scale up, since that does not fix the pull error.
4. Separately, triage the other unhealthy demo workloads: checkout (CrashLoop, revision 2 removed the DATABASE_URL env var from container app 48s ago, which is a likely bad_rollout) and reports (OOMKilled in container app, exit 137, memory limit likely too low).

Runbook: `image-pull`

**Tool calls**
1. `kubernetes_describe_pod`
2. `kubernetes_list_pods`
3. `kubernetes_recent_changes`
4. `runbooks_runbook_for_alert`
5. `kubernetes_describe_deployment`
