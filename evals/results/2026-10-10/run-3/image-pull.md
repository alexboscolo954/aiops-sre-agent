## Pod frontend-79765fc9d-pqg7h is not ready because its image, nginx:1.99.99-does-not-exist, cannot be pulled (ErrImagePull, NotFound). The frontend deployment has 0 of 1 replicas available.

**Root cause** (high confidence, `image_pull`): The frontend deployment references the nonexistent image tag nginx:1.99.99-does-not-exist. The registry returns 'not found', so the container never starts. This is the deployment's first revision, so there is no healthy older ReplicaSet to keep serving.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-79765fc9d-pqg7h

**Evidence**
- `kubernetes_list_pods`: frontend-79765fc9d-pqg7h is Pending 0/1, container web waiting in ErrImagePull: 'failed to resolve reference docker.io/library/nginx:1.99.99-does-not-exist: not found'
- `kubernetes_describe_deployment`: frontend has 0/1 ready replicas, Available=False (MinimumReplicasUnavailable). Image is nginx:1.99.99-does-not-exist. Only revision 1 exists, created about 41s ago.
- `runbooks_runbook_for_alert`: The image-pull runbook says a 'manifest unknown/not found' error means the tag does not exist. The fix is to correct the tag or roll back.

**Recommended actions**
1. Update the frontend deployment to a valid nginx tag, e.g. kubectl -n demo set image deployment/frontend web=nginx:<valid-tag>.
2. Check the CI or manifest source that set 1.99.99-does-not-exist and fix it there, so the bad tag is not redeployed.
3. Because this is revision 1, there is nothing to roll back to. Frontend is fully unavailable until the image is fixed.
4. Separately, other pods in the demo namespace are unhealthy. checkout-7c856f898c-bjtfx is exiting with code 1, and reports-7cc9978bbf-sq7r7 was OOMKilled. I did not investigate these, and they are likely separate alerts.

Runbook: `image-pull`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_deployment`
4. `kubernetes_json_placeholder`
