## Pod frontend-6f6b4986b9-hxdf2 is not ready because its only container, nginx, references the tag nginx:1.99.99-does-not-exist, which does not exist in the registry, so the kubelet sits in ErrImagePull/ImagePullBackOff. The frontend deployment was created about 2 minutes ago with this as its only revision, so there is no earlier working revision to roll back to; the fix is a valid image tag.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment's only revision (revision 1, ReplicaSet frontend-6f6b4986b9, created 2m ago) uses image nginx:1.99.99-does-not-exist. The pod events show 'Failed to pull image ... docker.io/library/nginx:1.99.99-does-not-exist: not found', and the container is in waiting state ErrImagePull. The pod has restarts 0 and has never run. The tag is a non-existent nginx version, which points to a typo or a bad tag in the manifest. No prior revision exists, so this is not a regression from an earlier working version.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-6f6b4986b9-hxdf2

**Evidence**
- `kubernetes_describe_pod`: frontend-6f6b4986b9-hxdf2 phase Pending, container web waiting ErrImagePull; message 'docker.io/library/nginx:1.99.99-does-not-exist: not found'; Ready=False ContainersNotReady; restarts 0.
- `kubernetes_describe_pod`: Events: 'Failed to pull image nginx:1.99.99-does-not-exist', 'Error: ImagePullBackOff', 'Back-off pulling image'.
- `kubernetes_describe_deployment`: frontend replicas desired 1, ready 0; Available=False MinimumReplicasUnavailable; rollout_history has only revision 1 (created 2m ago) with image nginx:1.99.99-does-not-exist.
- `kubernetes_recent_changes`: frontend revision 1 'created' 2m ago with no diff; no earlier revision exists to compare against.
- `runbooks_runbook_for_alert`: Matched runbooks deployment-unavailable and image-pull. The image-pull runbook lists 'manifest unknown / not found' as a non-existent tag, typically a typo or a tag CI never pushed.
- `incidents_search`: No past Report in the last 90 days matches frontend or nginx image pull issues.

**Recommendations**
1. Confirm the intended nginx tag with the frontend owner. Use an existing tag, for example nginx:1.25 or another tag confirmed in the registry, and correct the image in the frontend deployment manifest (GitOps source or kubectl set image deployment/frontend web=nginx:<valid-tag> -n demo).
2. Watch the rollout with kubectl rollout status deployment/frontend -n demo and confirm the pod reaches Ready 1/1.
3. Add CI validation that checks the image tag exists before deploy, so a non-existent tag cannot reach the cluster again.
4. Separate finding: the checkout deployment (revision 2, 48s ago) removed the DATABASE_URL env var from container app. Its pod checkout-869fc5bcc6-db5ps is CrashLooping with exit code 1 and 3 restarts. This is outside this alert but needs its own triage: restore DATABASE_URL or roll back checkout to revision 1.

Runbook: `image-pull`

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "frontend-6f6b4986b9-hxdf2"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": ""}
3. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
4. `runbooks_runbook_for_alert` {"alertname": "KubePodNotReady"}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "frontend"}
6. `incidents_search` {"keywords": "frontend nginx image pull", "days": 90, "limit": 5}
