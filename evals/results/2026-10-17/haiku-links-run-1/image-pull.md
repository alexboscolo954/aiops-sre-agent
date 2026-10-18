## The frontend pod frontend-79765fc9d-pqg7h is stuck in ErrImagePull/ImagePullBackOff because its only container uses the non-existent tag nginx:1.99.99-does-not-exist. The deployment has 0 of 1 replicas ready, and there is no earlier ReplicaSet serving traffic, so the frontend is fully unavailable.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment's container image tag nginx:1.99.99-does-not-exist does not exist in docker.io/library/nginx. The registry returns NotFound, so the kubelet cannot pull the image. This is a typo or an unpublished tag in the deployment spec. The deployment has only revision 1, so there is no prior working revision to fall back on.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-79765fc9d-pqg7h

**Evidence**
- `kubernetes_describe_pod`: Container web image nginx:1.99.99-does-not-exist, state waiting ErrImagePull; message: "failed to resolve reference docker.io/library/nginx:1.99.99-does-not-exist: not found"; Ready=False, ContainersNotReady.
- `kubernetes_get_events`: Warning Failed events for pod frontend-79765fc9d-pqg7h: "Failed to pull image ... not found", "Error: ErrImagePull", then "Error: ImagePullBackOff".
- `kubernetes_describe_deployment`: Replicas desired 1, ready 0; condition Available=False MinimumReplicasUnavailable; rollout_history has only revision 1 (frontend-79765fc9d) using nginx:1.99.99-does-not-exist.
- `runbooks_read_runbook (image-pull)`: Runbook says a 'not found' pull error means the tag does not exist (typo or CI never pushed it); fix the tag, the pull secret, or roll back.

**Recommendations**
1. Correct the frontend deployment image to a tag that exists, for example a valid nginx release such as nginx:1.25 or whatever tag the team actually publishes. Check the intended tag with the owning team or the CI pipeline first.
2. After the change, confirm the new ReplicaSet rolls out and the pod reaches Ready, and that the KubePodNotReady alert clears.
3. There is no previous revision to roll back to, so rolling back is not an option. Fixing the tag is the only path to recovery.
4. Add a CI check or admission policy that verifies image tags exist before a deployment is applied, so a non-existent tag does not reach the cluster again.

Runbook: `image-pull`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_describe_pod`
3. `kubernetes_get_events`
4. `kubernetes_describe_deployment`
5. `runbooks_read_runbook`
