## Pod frontend-79765fc9d-pqg7h can't start because its image tag nginx:1.99.99-does-not-exist doesn't exist in the registry (ErrImagePull, NotFound). The frontend deployment has 0 of 1 replicas ready.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment references the nonexistent image tag nginx:1.99.99-does-not-exist. The pull fails with 'not found', so the container never starts and the pod never becomes ready. This is the only ReplicaSet revision, so no earlier healthy revision is still serving.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-79765fc9d-pqg7h

**Evidence**
- `kubernetes_list_pods`: frontend-79765fc9d-pqg7h is Pending 0/1, web container waiting in ErrImagePull: failed to resolve reference docker.io/library/nginx:1.99.99-does-not-exist: not found
- `kubernetes_describe_deployment`: frontend has 0/1 ready replicas and Available=False (MinimumReplicasUnavailable). The only revision (1) uses image nginx:1.99.99-does-not-exist.

**Recommended actions**
1. Set the frontend image to a valid nginx tag, for example a known 1.x release or the tag the CI pipeline actually pushed, then re-apply the deployment.
2. Confirm the tag exists in the registry before deploying, for example by adding a CI check.
3. After the fix, check that the pod becomes Ready and the Available condition returns to True.
4. Separately, checkout (crash with exit code 1) and reports (OOMKilled) in the same namespace are also unhealthy. They look unrelated to this alert and should be triaged on their own.

Runbook: `image-pull`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_deployment`
