## Pod frontend-79765fc9d-pqg7h is not ready because it cannot pull its image. The tag nginx:1.99.99-does-not-exist does not exist, so the pod is stuck in ErrImagePull. The frontend deployment has 0/1 replicas available.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment references the nonexistent image tag nginx:1.99.99-does-not-exist. The registry returns 'not found', so the container never starts. This is the only revision in the rollout history, so there is no earlier working revision to compare against or roll back to.
**Severity:** medium  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-79765fc9d-pqg7h

**Evidence**
- `kubernetes_list_pods`: frontend-79765fc9d-pqg7h is Pending 0/1 with web waiting in ErrImagePull: 'docker.io/library/nginx:1.99.99-does-not-exist: not found'
- `kubernetes_describe_deployment`: frontend uses image nginx:1.99.99-does-not-exist. It has 0/1 ready replicas, Available=False (MinimumReplicasUnavailable), and only revision 1 exists.
- `runbooks_runbook_for_alert`: The image-pull runbook covers 'manifest unknown / not found': the tag does not exist. The fix is to correct the tag.

**Recommendations**
1. Set the frontend deployment image to a valid nginx tag, for example nginx:1.27 or the version the team intended, then confirm the pod becomes Ready.
2. Check the CI or manifest source for where the 1.99.99 tag came from, and add a check that the image exists before deploy.
3. Because this is the first revision, there is nothing to roll back to and the frontend has no serving replica. Treat it as a full frontend outage until the tag is fixed.
4. Separately, other pods in the demo namespace are also unhealthy: checkout-7c856f898c-bjtfx exits with code 1 and reports-7cc9978bbf-sq7r7 is OOMKilled. They are unrelated to this alert and need their own triage.

Runbook: `image-pull`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_deployment`
