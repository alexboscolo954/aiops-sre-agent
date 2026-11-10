## The frontend pod frontend-6f6b4986b9-hxdf2 never becomes ready because its image tag nginx:1.99.99-does-not-exist does not exist in the registry (ErrImagePull/ImagePullBackOff, 'not found'). frontend has only one revision, so no older ReplicaSet is serving. The deployment is fully down at 0/1 ready.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment was created about 2m ago with only revision 1, and that revision points container 'web' at image nginx:1.99.99-does-not-exist. The registry answers 'docker.io/library/nginx:1.99.99-does-not-exist: not found' (rpc NotFound), so the kubelet can't pull it and the container never starts. The tag is wrong or was never pushed. There is no earlier working revision to fall back on, so the deployment shows Available=False (MinimumReplicasUnavailable). One brief FailedScheduling event (untolerated taint) appeared at first, but the pod was scheduled after that, so scheduling isn't the problem.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend

**Evidence**
- `kubernetes_list_pods`: frontend-6f6b4986b9-hxdf2 is Pending, 0/1 ready, container 'web' waiting ErrImagePull: 'docker.io/library/nginx:1.99.99-does-not-exist: not found'
- `kubernetes_describe_pod`: Image nginx:1.99.99-does-not-exist. Events: Failed to pull image (rpc NotFound), ErrImagePull, then Back-off pulling image / ImagePullBackOff (x2). Pod was scheduled to squero-control-plane
- `kubernetes_describe_deployment`: frontend has desired 1, ready 0, Available=False MinimumReplicasUnavailable. Rollout history has only revision 1 (frontend-6f6b4986b9, created 2m ago) with image nginx:1.99.99-does-not-exist, so there's no previous working revision
- `kubernetes_recent_changes`: frontend revision 1 was created 2m ago, and no other rollout touched frontend. The checkout and reports problems are separate (checkout rev 2 removed DATABASE_URL; reports is OOMKilled)

**Recommendations**
1. Correct the frontend image to a tag that exists, e.g. a real nginx release your team has approved, in the manifest or source of truth, then redeploy. A rollback won't help because there is no earlier revision.
2. Check that the tag exists in docker.io before applying, and find out why CI or the manifest produced '1.99.99-does-not-exist'.
3. Watch the new pod: the image should pull, the pod should reach Running and 1/1 Ready, and the deployment should show Available=True.
4. Triage separately the other unhealthy demo workloads seen during this check: checkout is crash looping since rev 2 removed DATABASE_URL, and reports is OOMKilled.

Runbook: `image-pull`

**Tool calls**
1. `runbooks_runbook_for_alert` {"alertname": "KubePodNotReady"}
2. `kubernetes_list_pods` {"cluster": "kind", "namespace": "demo"}
3. `kubernetes_describe_pod` {"cluster": "kind", "namespace": "demo", "name": "frontend-6f6b4986b9-hxdf2"}
4. `kubernetes_recent_changes` {"cluster": "kind"}
5. `incidents_search` {"keywords": "frontend KubePodNotReady"}
6. `kubernetes_describe_deployment` {"cluster": "kind", "namespace": "demo", "name": "frontend"}
