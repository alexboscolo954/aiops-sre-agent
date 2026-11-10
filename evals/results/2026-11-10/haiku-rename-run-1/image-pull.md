## Pod frontend-6f6b4986b9-hxdf2 is not ready because its only container, nginx, uses the tag nginx:1.99.99-does-not-exist, which does not exist on Docker Hub, so the pull fails with ErrImagePull/ImagePullBackOff. The frontend deployment has no working revision, so nothing is serving and the alert is real. A separate problem in checkout (revision 2 removed DATABASE_URL, pods crash with exit 1) is not the cause of this alert but needs its own look.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment's single revision (revision 1, ReplicaSet frontend-6f6b4986b9, created about 2m ago) sets the container image to nginx:1.99.99-does-not-exist. The registry returns 'failed to resolve reference ... not found', so the pod stays Pending with ErrImagePull and ImagePullBackOff and never becomes Ready. The tag is almost certainly a typo or a version that was never published. There is no earlier revision that worked, so this is not a rollback-able regression. The deployment has 0 of 1 replicas ready and MinimumReplicasUnavailable is set.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-6f6b4986b9-hxdf2

**Evidence**
- `kubernetes_describe_pod`: frontend-6f6b4986b9-hxdf2 phase Pending, container web waiting ErrImagePull; message 'docker.io/library/nginx:1.99.99-does-not-exist: not found'; events show Failed and BackOff with ImagePullBackOff.
- `kubernetes_describe_deployment`: frontend replicas desired 1, ready 0; Available=False MinimumReplicasUnavailable; rollout_history has only revision 1 with images [nginx:1.99.99-does-not-exist].
- `kubernetes_list_pods`: frontend-6f6b4986b9-hxdf2 age 2m, ready 0/1, restarts 0, waiting ErrImagePull.
- `kubernetes_recent_changes`: frontend revision 1 'created' 2m ago with no diff, so the bad tag was in the first deployment and there is no prior working revision to roll back to.
- `runbooks_runbook_for_alert`: KubePodNotReady maps to the deployment-unavailable and image-pull runbooks. The image-pull runbook says a 'not found' message means the tag does not exist (typo or never pushed), and the fix is to correct the tag or roll back.

**Recommendations**
1. Confirm the intended image tag with the owners of the frontend manifest or CI pipeline. Check which nginx tags exist in the registry (for example nginx:1.25 or nginx:latest) and do not guess.
2. Update the frontend deployment's container image to a valid, published tag. This is a change, so it needs approval. Then watch the rollout until frontend-6f6b4986b9-hxdf2 or its replacement is Ready.
3. Fix the source manifest or GitOps values so the bad tag is not reapplied on the next sync.
4. Separately triage demo/checkout: revision 2 removed the DATABASE_URL env var from container app, and pod checkout-869fc5bcc6-db5ps is crash-looping with exit code 1. Rolling checkout back to revision 1 is the likely fix, but it needs its own approval.
5. Pod reports-55b4fffc66-hmq7f is also not ready with OOMKilled (exit 137). It is a separate issue and should be checked on its own.

Runbook: `image-pull`

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "frontend-6f6b4986b9-hxdf2"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": ""}
3. `runbooks_runbook_for_alert` {"alertname": "KubePodNotReady"}
4. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "frontend"}
6. `incidents_search` {"keywords": "frontend ImagePullBackOff nginx image tag", "days": 90, "limit": 5}
