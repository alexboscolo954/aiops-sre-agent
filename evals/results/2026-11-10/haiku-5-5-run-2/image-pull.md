## The frontend pod frontend-6f6b4986b9-hxdf2 is not ready because its only container image, nginx:1.99.99-does-not-exist, does not exist in the registry, so the pod is stuck in ErrImagePull/ImagePullBackOff. The frontend deployment has 0 of 1 desired replicas ready. This is a bad image tag, not a capacity or app problem.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment (revision 1, the only revision) references image tag nginx:1.99.99-does-not-exist. The registry returns "not found" for docker.io/library/nginx:1.99.99-does-not-exist, so kubelet cannot pull it and the pod stays in ErrImagePull/ImagePullBackOff. The tag looks like a typo or a version that was never published. Because this is the first revision, there is no earlier working ReplicaSet for frontend, so the frontend service has no ready pods at all.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-6f6b4986b9-hxdf2

**Evidence**
- `kubernetes_describe_pod`: Pod frontend-6f6b4986b9-hxdf2 container 'web' image nginx:1.99.99-does-not-exist, state waiting ErrImagePull; message: 'failed to resolve reference docker.io/library/nginx:1.99.99-does-not-exist: not found'. Events show ImagePullBackOff with count 2.
- `kubernetes_describe_deployment`: Deployment frontend: replicas desired 1, ready 0; Available=False MinimumReplicasUnavailable; rollout_history has only revision 1 (ReplicaSet frontend-6f6b4986b9, created 2m ago) with image nginx:1.99.99-does-not-exist.
- `kubernetes_list_pods`: frontend-6f6b4986b9-hxdf2 phase Pending, ready 0/1, waiting ErrImagePull, age 2m.
- `kubernetes_recent_changes`: frontend revision 1 created 2m ago with no diff; no other rollouts relate to frontend.
- `runbooks_read_runbook`: image-pull runbook: 'not found' means the tag does not exist (typo or CI never pushed it); fix the tag or roll back.

**Recommendations**
1. Confirm the intended frontend image tag with the owning team. Typical fix: set the deployment image to a published tag, e.g. kubectl -n demo set image deployment/frontend web=nginx:<valid-tag>.
2. Check the CI/CD pipeline or manifest that produced the tag, to find out why the bad version was deployed.
3. Because there is no previous working revision, rollback is not possible. Fixing the tag is the only remedy.
4. Verify the rollout: the frontend pod should move to Running and Ready, and the KubePodNotReady alert should resolve.
5. Separately, checkout and reports in the same namespace are also unhealthy (checkout: DATABASE_URL removed in revision 2; reports: OOMKilled). They are not part of this alert group and need their own triage.

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodNotReady"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_recent_changes` {"cluster": "kind"}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "frontend"}
5. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "frontend-6f6b4986b9-hxdf2"}
6. `runbooks_read_runbook` {"name": "image-pull"}
7. `incidents_search` {"keywords": "frontend nginx image pull"}
8. `TriageReport` {"summary": "The frontend pod frontend-6f6b4986b9-hxdf2 is not ready because its only container image, nginx:1.99.99-does-not-exist, does not exist in the registry, so the pod is stuck in ErrImagePull/ImagePullBackOff. The frontend deployment has 0 of 1 desired replicas ready. This is a bad image ta
