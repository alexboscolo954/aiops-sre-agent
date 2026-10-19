## The frontend pod is stuck in ErrImagePull/ImagePullBackOff because its only revision references the nonexistent tag nginx:1.99.99-does-not-exist, so frontend has 0 of 1 replicas ready. The same namespace also has checkout crash-looping after its latest rollout removed DATABASE_URL, and reports OOMKilling; those are separate problems.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment's only revision (revision 1, created about 2m ago) uses image nginx:1.99.99-does-not-exist. The registry returns NotFound for docker.io/library/nginx:1.99.99-does-not-exist, so the pod stays Pending with ErrImagePull and then ImagePullBackOff. The tag was most likely a typo or was never published. There is no earlier working frontend revision to fall back to, so the deployment has never been available.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-6f6b4986b9-hxdf2

**Evidence**
- `kubernetes_list_pods`: frontend-6f6b4986b9-hxdf2 is Pending, 0/1 ready, restarts 0, age 2m; container web is waiting with ErrImagePull: manifest for nginx:1.99.99-does-not-exist not found.
- `kubernetes_describe_deployment`: frontend has desired=1, ready=0; image nginx:1.99.99-does-not-exist; Available=False with reason MinimumReplicasUnavailable; rollout_history has only revision 1 (created 2m ago).
- `kubernetes_get_events`: Warning events on Pod/frontend-6f6b4986b9-hxdf2: 'Failed to pull image "nginx:1.99.99-does-not-exist" ... not found' and 'Error: ImagePullBackOff'.
- `kubernetes_recent_changes`: frontend revision 1 was created 2m ago, with no earlier revision. Other demo changes are checkout revision 2 (DATABASE_URL removed, 48s ago) and reports revision 1 (2m ago).

**Recommendations**
1. Correct the frontend image tag to a published nginx tag (for example nginx:1.27 or whichever version CI intended), then roll out the fix through the normal GitOps or Helm path. Do not patch the live Deployment by hand.
2. Confirm the tag exists in the registry before redeploying, and add a CI check that fails when the image tag does not resolve.
3. Since this is the only frontend revision, there is no older ReplicaSet to roll back to. Frontend stays down until a valid tag is deployed.
4. Separately, investigate checkout: revision 2 removed the DATABASE_URL env var and the pod exits with code 1 (CrashLoopBackOff). Restore the variable or roll back to revision 1.
5. Separately, investigate reports: the container is OOMKilled (exit 137) and its memory limit is likely too low. Check its limits against actual usage.

Runbook: `image-pull`

**Tool calls**
1. `kubernetes_list_pods`
2. `runbooks_runbook_for_alert`
3. `kubernetes_recent_changes`
4. `kubernetes_describe_deployment`
5. `kubernetes_get_events`
