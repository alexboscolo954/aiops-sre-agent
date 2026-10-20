## Pod frontend-6f6b4986b9-hxdf2 is not ready because its only container, web, uses the nonexistent image nginx:1.99.99-does-not-exist, so the kubelet gets ErrImagePull and then ImagePullBackOff. The frontend deployment has only revision 1, so it has never run a working version. Fixing the image tag should resolve the alert.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment's only revision (revision 1, created about 2m before triage) sets the container image to nginx:1.99.99-does-not-exist. The registry returns NotFound ("docker.io/library/nginx:1.99.99-does-not-exist: not found"), so the pod stays in ErrImagePull/ImagePullBackOff and never becomes ready. The deployment has 0 of 1 desired replicas ready, with Available=False reason MinimumReplicasUnavailable. This is a bad tag, not a bad rollout: there is no earlier revision that worked.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-6f6b4986b9-hxdf2

**Evidence**
- `kubernetes_describe_pod`: Pod frontend-6f6b4986b9-hxdf2 is Pending. Container web is waiting with ErrImagePull, image nginx:1.99.99-does-not-exist, and Ready=False (ContainersNotReady). The event message is "failed to resolve reference ... nginx:1.99.99-does-not-exist: not found".
- `kubernetes_describe_pod`: Events show Failed/ErrImagePull and BackOff "Back-off pulling image", with restarts 0. The pod was scheduled on aiops-control-plane.
- `kubernetes_describe_deployment`: frontend has desired=1, ready=0. rollout_history has a single revision 1 (ReplicaSet frontend-6f6b4986b9, created 2m ago) with images [nginx:1.99.99-does-not-exist]. Condition Available=False, MinimumReplicasUnavailable.
- `kubernetes_recent_changes`: frontend revision 1 was "created" 2m ago with an empty diff, so there is no earlier revision to roll back to.
- `runbooks_runbook_for_alert`: KubePodNotReady maps to the deployment-unavailable runbook, and image-pull is the matching runbook for ErrImagePull. Both say a bad tag is the usual cause and to fix the tag or roll back.

**Recommendations**
1. Correct the frontend image tag to a version that exists (for example, the intended nginx tag, checked against the registry), via a new revision of the frontend deployment. Changing the image is a configuration change, so have an operator apply it.
2. Confirm the new ReplicaSet's pod reaches Ready and that frontend shows 1/1 ready.
3. Add a CI or admission check that rejects image tags that do not resolve before they reach the cluster.
4. Separately, the checkout deployment's revision 2 (rolled out 48s before triage) removed the DATABASE_URL env var from the app container. This is unrelated to the frontend alert, but it is a likely outage risk for checkout and should be checked.

Runbook: `image-pull`

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "frontend-6f6b4986b9-hxdf2"}
2. `runbooks_runbook_for_alert` {"alertname": "KubePodNotReady"}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "frontend"}
