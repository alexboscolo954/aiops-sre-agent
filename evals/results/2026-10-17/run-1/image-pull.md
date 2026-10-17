## Pod frontend-79765fc9d-pqg7h is stuck in ErrImagePull. The frontend deployment references image nginx:1.99.99-does-not-exist, and that tag does not exist on Docker Hub. The deployment has 0 of 1 replicas ready.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment is configured with a nonexistent image tag, nginx:1.99.99-does-not-exist, so the kubelet cannot pull it. The deployment has only one revision, so there is no earlier working ReplicaSet to keep serving. The frontend is fully unavailable.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-79765fc9d-pqg7h

**Evidence**
- `kubernetes_list_pods`: frontend-79765fc9d-pqg7h is Pending 0/1 with web waiting in ErrImagePull: docker.io/library/nginx:1.99.99-does-not-exist: not found
- `kubernetes_describe_deployment`: The frontend deployment has 0 of 1 replicas ready, condition Available=False (MinimumReplicasUnavailable), and the image is nginx:1.99.99-does-not-exist
- `kubernetes_describe_deployment`: Rollout history shows a single revision (1), created about 41s ago, with the bad tag. No previous good revision exists to roll back to.
- `runbooks_runbook_for_alert`: The image-pull runbook says a 'not found' error means the tag does not exist. Fix the tag or roll back.

**Recommendations**
1. Set the frontend image to a valid nginx tag, for example kubectl -n demo set image deploy/frontend web=nginx:<valid-tag>. Pin a known-good version such as nginx:1.27.
2. Fix the source manifest or CI so the bad tag is not reapplied.
3. Check with kubectl rollout status that the new pod becomes Ready.
4. Add a CI check that the image tag exists in the registry before deploy.
5. Other pods in demo are also unhealthy: checkout-7c856f898c-bjtfx is in Error with exit code 1, and reports-7cc9978bbf-sq7r7 is OOMKilled. These are separate from this alert and should be triaged on their own.

Runbook: `image-pull`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_deployment`
