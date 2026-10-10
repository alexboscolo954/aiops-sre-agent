## Pod frontend-79765fc9d-lpl82 is not ready because its image, nginx:1.99.99-does-not-exist, can't be pulled (ErrImagePull, not found). The frontend deployment has 0 of 1 replicas available.

**Root cause** (high confidence, `image_pull`): The frontend deployment references a nonexistent image tag, nginx:1.99.99-does-not-exist. The registry returns NotFound, so the container never starts.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-79765fc9d-lpl82

**Evidence**
- `kubernetes_list_pods`: frontend-79765fc9d-lpl82 is Pending 0/1 with web waiting in ErrImagePull: failed to resolve reference docker.io/library/nginx:1.99.99-does-not-exist: not found
- `kubernetes_describe_deployment`: frontend has 0 of 1 replicas ready and condition Available=False (MinimumReplicasUnavailable). Its only revision (1) uses image nginx:1.99.99-does-not-exist.
- `kubernetes_describe_deployment`: There is no earlier healthy ReplicaSet, so nothing is serving frontend traffic. Impact is full, not limited.

**Recommended actions**
1. Set the frontend image to a valid nginx tag, for example with `kubectl set image deploy/frontend web=nginx:<valid-tag> -n demo`. Fix the source manifest or CI as well.
2. Check the pipeline or manifest that produced the 1.99.99 tag, since it may be a typo or an image that was never pushed.
3. After the fix, confirm the pod reaches Ready and the Available condition returns to True.
4. Separate from this alert, checkout-7c856f898c-bsjvj is erroring with exit code 1 and reports-7cc9978bbf-ddp5d is OOMKilled in the same namespace. I did not investigate either, so they need their own triage.

Runbook: `image-pull`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_deployment`
4. `runbooks_read_runbook`
