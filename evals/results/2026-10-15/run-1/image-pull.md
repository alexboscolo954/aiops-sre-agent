## The frontend pod frontend-79765fc9d-pqg7h can't start because its image tag nginx:1.99.99-does-not-exist doesn't exist, so it is stuck in ErrImagePull. The frontend deployment has 0 of 1 replicas available.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment references the non-existent image tag docker.io/library/nginx:1.99.99-does-not-exist. The registry returns NotFound, so the container never starts and the pod never becomes ready. This looks like a typo or an unpublished tag. Revision 1 is the only revision, so there is no earlier working ReplicaSet to fall back on.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-79765fc9d-pqg7h

**Evidence**
- `kubernetes_list_pods`: frontend-79765fc9d-pqg7h is Pending 0/1 with web waiting in ErrImagePull: failed to resolve reference "docker.io/library/nginx:1.99.99-does-not-exist": not found
- `kubernetes_describe_deployment`: The frontend deployment runs image nginx:1.99.99-does-not-exist with 0 of 1 replicas ready. Available=False (MinimumReplicasUnavailable). Revision 1 is the only revision.
- `runbooks_runbook_for_alert`: The image-pull runbook says a 'manifest unknown / not found' error means the tag doesn't exist (typo, or CI never pushed it).

**Recommendations**
1. Set the frontend deployment's image to a valid nginx tag, for example a pinned 1.27.x tag or a tag your CI has actually pushed. For example, run: kubectl -n demo set image deploy/frontend web=nginx:<valid-tag>.
2. Check the manifest or CI pipeline source for the bad tag 1.99.99-does-not-exist and correct it there, so a later apply doesn't bring it back.
3. Once the image is fixed, confirm the pod reaches Ready and the Available condition clears.
4. The demo namespace also has checkout (exit code 1) and reports (OOMKilled) pods that are not ready. They look like separate issues, so triage them on their own.

Runbook: `image-pull`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_deployment`
