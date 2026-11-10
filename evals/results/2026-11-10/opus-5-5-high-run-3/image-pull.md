## The frontend deployment in demo is down (0/1 ready). Its only pod, frontend-6f6b4986b9-hxdf2, can't start because the image tag nginx:1.99.99-does-not-exist doesn't exist on Docker Hub, so the pull fails with ErrImagePull.

**Root cause** (high confidence, `image_unavailable`): The deployment's container 'web' uses image nginx:1.99.99-does-not-exist. The registry says it is 'not found' ("failed to resolve reference docker.io/library/nginx:1.99.99-does-not-exist: not found"), so the pod stays Pending with ErrImagePull. The deployment has only one revision (frontend-6f6b4986b9, created 2m ago), and that revision has always used this tag. There is no older ReplicaSet still serving and no earlier revision that worked, so frontend is fully unavailable (Available=False, MinimumReplicasUnavailable).
**Severity:** high  ·  **Affected:** demo/Deployment/frontend

**Evidence**
- `kubernetes_list_pods`: frontend-6f6b4986b9-hxdf2 is Pending, 0/1 ready, container web waiting ErrImagePull: 'docker.io/library/nginx:1.99.99-does-not-exist: not found'
- `kubernetes_describe_deployment`: frontend image nginx:1.99.99-does-not-exist, replicas desired 1 / ready 0, Available=False (MinimumReplicasUnavailable), only rollout revision 1 (frontend-6f6b4986b9, 2m old) so nothing older is serving
- `runbooks_runbook_for_alert`: The image-pull runbook says a 'not found' error means the tag doesn't exist (a typo, or CI never pushed it). Fix: correct the tag or roll back.

**Recommendations**
1. Change the frontend deployment's image to a tag that exists (e.g. a released nginx version your team uses) through the deployment's source of truth (manifest/Helm/GitOps), e.g. kubectl -n demo set image deployment/frontend web=nginx:<valid-tag>.
2. Check that a new pod pulls the image and becomes Ready, and that the deployment reports Available=True.
3. Find out where the bad tag came from (a typo in the manifest, or a CI pipeline that never pushed the image). Add a CI check that the image exists before deploying.
4. Rolling back won't help: revision 1 is the only revision and has always used the bad tag.
5. Note: checkout (crashing with exit code 1) and reports (OOMKilled) in the same namespace are also unhealthy. They aren't part of this alert, but someone should look at them separately.

Runbook: `image-pull`

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
2. `runbooks_runbook_for_alert` {"alertname": "KubePodNotReady"}
3. `incidents_search` {"keywords": "frontend"}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "frontend"}
