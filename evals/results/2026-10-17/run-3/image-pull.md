## Pod frontend-79765fc9d-pqg7h is stuck in ErrImagePull because the deployment references the nonexistent image tag nginx:1.99.99-does-not-exist. The frontend has 0 ready replicas and is fully unavailable.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment is configured with image nginx:1.99.99-does-not-exist, and that tag is not in the registry. The kubelet cannot pull it, so the container never starts. This is the only revision, so no earlier ReplicaSet is serving traffic.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-79765fc9d-pqg7h

**Evidence**
- `kubernetes_list_pods`: frontend-79765fc9d-pqg7h is Pending 0/1, web container waiting with ErrImagePull: 'docker.io/library/nginx:1.99.99-does-not-exist: not found'
- `kubernetes_describe_deployment`: frontend has 0/1 ready, Available=False (MinimumReplicasUnavailable), image nginx:1.99.99-does-not-exist, and only one revision (revision 1)
- `runbooks_runbook_for_alert`: The image-pull runbook says a 'not found' error means the tag does not exist, and the fix is to correct the tag or roll back.

**Recommendations**
1. Set the frontend image to a valid nginx tag, for example with 'kubectl -n demo set image deploy/frontend web=nginx:<valid-tag>'. Fix it in the source manifest or CI as well.
2. Check the manifest or CI pipeline to find where the bad tag came from (typo or an unpublished tag).
3. After the fix, confirm the pod becomes Ready and the KubePodNotReady alert resolves.
4. Note that no healthy earlier revision exists, so a rollback is not possible and the frontend is fully down until the tag is fixed.
5. Separate from this alert, checkout-7c856f898c-bjtfx is crash-looping with exit code 1 and reports-7cc9978bbf-sq7r7 is OOMKilled in the same namespace. I did not investigate either, so both need their own triage.

Runbook: `image-pull`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_deployment`
