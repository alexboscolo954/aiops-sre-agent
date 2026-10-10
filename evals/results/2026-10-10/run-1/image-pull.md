## Pod frontend-79765fc9d-lpl82 is not ready because its image, nginx:1.99.99-does-not-exist, can't be pulled (ErrImagePull, NotFound). The frontend deployment has 0 of 1 replicas available.

**Root cause** (high confidence, `image_pull`): The frontend deployment references a nonexistent image tag (nginx:1.99.99-does-not-exist). The registry returns not found, so the container never starts. The tag is in revision 1, the only revision, so there is no earlier good revision to roll back to.
**Severity:** medium  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-79765fc9d-lpl82

**Evidence**
- `kubernetes_list_pods`: frontend-79765fc9d-lpl82 is Pending 0/1 with web waiting in ErrImagePull: failed to resolve reference docker.io/library/nginx:1.99.99-does-not-exist: not found
- `kubernetes_describe_deployment`: frontend uses image nginx:1.99.99-does-not-exist, is 0/1 ready, and has Available=False (MinimumReplicasUnavailable). Revision 1 is the only revision.

**Recommended actions**
1. Update the frontend deployment image to a valid nginx tag, for example a known stable version, with kubectl set image or by fixing the manifest in git.
2. Check that the rollout completes and the pod becomes Ready.
3. Add a CI check that the image tag exists before deploy.
4. Separately, other pods in demo are unhealthy: checkout-7c856f898c-bsjvj is crashing with exit code 1, and reports-7cc9978bbf-ddp5d is OOMKilled. They are not part of this alert, so triage them on their own.

Runbook: `deployment-unavailable`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_deployment`
