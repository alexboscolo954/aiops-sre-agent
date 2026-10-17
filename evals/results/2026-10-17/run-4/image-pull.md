## Pod frontend-79765fc9d-pqg7h is stuck in ErrImagePull because the deployment references the image nginx:1.99.99-does-not-exist, which doesn't exist. The frontend has 0 of 1 replicas available.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment is configured with a non-existent image tag, nginx:1.99.99-does-not-exist. The registry returns NotFound, so the container never starts and the pod stays not ready.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-79765fc9d-pqg7h

**Evidence**
- `kubernetes_list_pods`: frontend-79765fc9d-pqg7h is Pending 0/1 with web waiting in ErrImagePull: failed to resolve reference docker.io/library/nginx:1.99.99-does-not-exist: not found
- `kubernetes_describe_deployment`: The frontend deployment image is nginx:1.99.99-does-not-exist. Ready is 0 of 1, and the Available condition is False (MinimumReplicasUnavailable).
- `kubernetes_describe_deployment`: Rollout history has only revision 1, created about 41s ago, so there is no earlier working revision to roll back to. The frontend has probably never been available.

**Recommendations**
1. Set the frontend deployment image to a valid nginx tag, for example with `kubectl set image deployment/frontend web=nginx:<valid-tag> -n demo`.
2. Fix the tag at its source (manifest, Helm values or CI) so the bad tag is not redeployed.
3. Confirm the new pod pulls the image and becomes Ready, and that the alert clears.
4. Separate from this alert, the pods checkout-7c856f898c-bjtfx (Error, exit 1) and reports-7cc9978bbf-sq7r7 (OOMKilled) are also not ready in demo. Triage them on their own.

Runbook: `image-pull`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_deployment`
