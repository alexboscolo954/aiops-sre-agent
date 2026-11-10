## frontend can't start because its image tag nginx:1.99.99-does-not-exist doesn't exist on Docker Hub. Pod frontend-6f6b4986b9-hxdf2 is stuck in ErrImagePull and the deployment has 0 of 1 replicas ready. No older ReplicaSet is serving traffic, so frontend is fully down.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment's only revision (revision 1, ReplicaSet frontend-6f6b4986b9, created about 2 minutes ago) uses the image nginx:1.99.99-does-not-exist. The pull fails with 'docker.io/library/nginx:1.99.99-does-not-exist: not found'. That means the tag isn't in the registry; this is not an auth or network problem. There's no earlier working revision to fall back on, so the deployment shows Available=False (MinimumReplicasUnavailable).
**Severity:** high  ·  **Affected:** demo/Deployment/frontend

**Evidence**
- `kubernetes_list_pods`: frontend-6f6b4986b9-hxdf2 is Pending, 0/1 ready, container 'web' waiting with ErrImagePull: 'failed to resolve reference docker.io/library/nginx:1.99.99-does-not-exist: not found'
- `kubernetes_describe_deployment`: frontend has image nginx:1.99.99-does-not-exist, 0 of 1 replicas ready, Available=False MinimumReplicasUnavailable. Its rollout history holds only revision 1 (created 2m ago), so there's no earlier ReplicaSet to roll back to
- `runbooks_runbook_for_alert`: The image-pull runbook says a 'not found' message means the tag doesn't exist: fix the tag or roll back

**Recommendations**
1. Change the frontend deployment's image to a tag that exists (for example a released nginx version such as nginx:1.27), either in the source manifest or Helm values or with kubectl set image deployment/frontend web=<valid-tag> -n demo. A rollback won't help because revision 1 is the only one.
2. Check whatever pipeline or manifest set the 1.99.99-does-not-exist tag so it doesn't get re-applied.
3. Confirm the new pod pulls its image and goes Ready, and that the KubePodNotReady alert clears.
4. Separately, two other pods in demo are unhealthy and weren't part of this triage: checkout is restarting after exit code 1 and reports is being OOMKilled. Triage those on their own.

Runbook: `image-pull`

**Tool calls**
1. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
2. `runbooks_runbook_for_alert` {"alertname": "KubePodNotReady"}
3. `incidents_search` {"keywords": "frontend"}
4. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "frontend"}
