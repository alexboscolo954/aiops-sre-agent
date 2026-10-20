## Frontend pod frontend-6f6b4986b9-hxdf2 is not ready because its nginx image tag 1.99.99-does-not-exist does not exist on Docker Hub, so the kubelet cannot pull it (ErrImagePull/ImagePullBackOff). The deployment has no earlier working revision, so no other frontend pods serve traffic and the deployment has 0 of 1 replicas ready.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment's only revision (revision 1, created about 2m ago) sets container web to image nginx:1.99.99-does-not-exist. The registry returns 'not found' for docker.io/library/nginx:1.99.99-does-not-exist, so the pod stays in ErrImagePull/ImagePullBackOff and never becomes Ready. The tag looks like a typo or a version that was never published, not a registry outage. Because this is the first revision, there is no older ReplicaSet serving traffic.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-6f6b4986b9-hxdf2

**Evidence**
- `kubernetes_describe_pod`: Pod frontend-6f6b4986b9-hxdf2: container web image nginx:1.99.99-does-not-exist, state waiting ErrImagePull; message 'failed to resolve reference ... docker.io/library/nginx:1.99.99-does-not-exist: not found'; Ready=False ContainersNotReady; events show repeated ImagePullBackOff.
- `kubernetes_describe_deployment`: Deployment frontend: replicas desired 1 ready 0; Available=False MinimumReplicasUnavailable; single rollout_history revision 1 (created 2m) with images nginx:1.99.99-does-not-exist.
- `kubernetes_recent_changes`: frontend revision 1 'created' 2m ago with no earlier revision, so no prior working image to roll back to.
- `runbooks_runbook_for_alert`: KubePodNotReady maps to deployment-unavailable; its image-pull runbook says a 'not found' pull error means the tag does not exist and the fix is to correct the tag or roll back.

**Recommendations**
1. Confirm which nginx tag is intended (for example, an existing tag such as nginx:1.27 or the tag CI actually pushed), then update the frontend deployment image to that tag. This is a config change and needs human approval.
2. If the tag came from a CI or Helm values change, fix the source values so the next sync does not reintroduce the bad tag.
3. After the fix, confirm the pod reaches Ready and the deployment shows 1/1 available.
4. Note for the same namespace: the checkout deployment (revision 2, 48s ago) removed the DATABASE_URL env var, and checkout-869fc5bcc6-db5ps is crash-looping with exit code 1. Reports pod reports-55b4fffc66-hmq7f is OOMKilled. These are separate from this alert and were not investigated in depth here.

Runbook: `image-pull`

**Tool calls**
1. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "frontend-6f6b4986b9-hxdf2"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo", "label_selector": ""}
3. `runbooks_runbook_for_alert` {"alertname": "KubePodNotReady"}
4. `kubernetes_recent_changes` {"cluster": "kind", "since_minutes": 360}
5. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "frontend"}
6. `incidents_search` {"keywords": "frontend nginx image pull", "days": 90, "limit": 5}
