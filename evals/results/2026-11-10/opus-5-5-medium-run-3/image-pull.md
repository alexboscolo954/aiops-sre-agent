## The frontend pod frontend-6f6b4986b9-hxdf2 is stuck in Pending with ErrImagePull because the image tag nginx:1.99.99-does-not-exist does not exist on Docker Hub. The deployment has 0 of 1 replicas ready. Revision 1 is its only revision, so no older ReplicaSet is serving traffic.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment (revision 1, ReplicaSet frontend-6f6b4986b9, created about 2m before I checked) points its 'web' container at the image nginx:1.99.99-does-not-exist. Docker Hub has no such tag, and the pull fails with 'failed to resolve reference "docker.io/library/nginx:1.99.99-does-not-exist": not found'. The container can never start. This is a bad tag, not a registry auth or network problem.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend

**Evidence**
- `kubernetes_list_pods`: frontend-6f6b4986b9-hxdf2 is Pending, ready 0/1, container 'web' waiting ErrImagePull: 'docker.io/library/nginx:1.99.99-does-not-exist: not found'
- `kubernetes_describe_deployment`: frontend image nginx:1.99.99-does-not-exist, desired 1 / ready 0, Available=False (MinimumReplicasUnavailable); rollout history has only revision 1 (frontend-6f6b4986b9, 2m old), so there is no earlier working ReplicaSet to fall back on
- `runbooks_runbook_for_alert`: The image-pull runbook says 'not found' means the tag does not exist (a typo, or CI never pushed it); the fix is to correct the tag or roll back

**Recommendations**
1. Change the frontend deployment's 'web' container image to a valid nginx tag that exists (for example the intended pinned version, such as nginx:1.27). Do this in the source manifest or GitOps repo so the fix sticks, then apply it (e.g. kubectl -n demo set image deployment/frontend web=nginx:<valid-tag>).
2. Watch the rollout: kubectl -n demo rollout status deployment/frontend. Then confirm the pod becomes Ready and the KubePodNotReady alert resolves.
3. Add a CI/admission check that the image tag exists before deploying, so this doesn't happen again.
4. This is outside this alert, but other workloads in demo are also unhealthy: checkout is crash-looping with exit code 1, and reports is being OOMKilled. Triage them separately.

Runbook: `image-pull`

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
2. `runbooks_runbook_for_alert` {"alertname": "KubePodNotReady"}
3. `incidents_search` {"keywords": "frontend"}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "frontend"}
