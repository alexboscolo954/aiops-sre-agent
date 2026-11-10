## frontend pod frontend-6f6b4986b9-hxdf2 is stuck in ErrImagePull because its only deployment revision references nginx:1.99.99-does-not-exist, a tag that does not exist on Docker Hub. The deployment has 0 of 1 ready replicas and has been unavailable since it was created about 2 minutes ago. This is a bad image tag, not a capacity or app problem.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment (revision 1, the only revision) sets container web to image nginx:1.99.99-does-not-exist. The pod event shows the registry returned "not found" for docker.io/library/nginx:1.99.99-does-not-exist, so the kubelet cannot start the container. The tag is a typo or was never published. There is no earlier working revision, so no previous image is serving traffic for this workload.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-6f6b4986b9-hxdf2

**Evidence**
- `kubernetes_list_pods`: frontend-6f6b4986b9-hxdf2 Pending, 0/1 ready, container web waiting with ErrImagePull: "docker.io/library/nginx:1.99.99-does-not-exist: not found"
- `kubernetes_describe_deployment`: frontend image nginx:1.99.99-does-not-exist; Available=False MinimumReplicasUnavailable; rollout_history has only revision 1 (created 2m ago)
- `kubernetes_pod_logs`: Logs unavailable: container web is waiting to start, image can't be pulled

**Recommendations**
1. Confirm the intended nginx tag (for example nginx:1.27 or another published version) with the team that owns the frontend manifest.
2. Correct the image in the frontend deployment manifest and roll it out. This is a config change, so it needs a human to apply it.
3. Since this is the first revision, a rollback is not possible. Fixing the tag is the only path to a ready pod.
4. Check that the pod becomes Ready and that the KubePodNotReady alert clears.

Runbook: `image-pull`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodNotReady"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "frontend"}
5. `kubernetes_pod_logs` {"cluster": "kind", "namespace": "demo", "name": "frontend-6f6b4986b9-hxdf2"} (error)
6. `incidents_search` {"keywords": "frontend ErrImagePull nginx image"}
7. `TriageReport` {"summary": "frontend pod frontend-6f6b4986b9-hxdf2 is stuck in ErrImagePull because its only deployment revision references nginx:1.99.99-does-not-exist, a tag that does not exist on Docker Hub. The deployment has 0 of 1 ready replicas and has been unavailable since it was created about 2 minutes a
