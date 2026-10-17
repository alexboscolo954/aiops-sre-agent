## Pod frontend-79765fc9d-pqg7h is not ready because its image nginx:1.99.99-does-not-exist can't be pulled (ErrImagePull, NotFound). The frontend deployment has 0/1 ready replicas.

**Root cause** (high confidence, `image_unavailable`): The frontend deployment references a non-existent image tag, nginx:1.99.99-does-not-exist. The registry returns 'not found', so the container never starts. This is the deployment's only revision, so there is no earlier working version to fall back to.
**Severity:** high  ·  **Affected:** demo/Deployment/frontend, demo/Pod/frontend-79765fc9d-pqg7h

**Evidence**
- `kubernetes_list_pods`: frontend-79765fc9d-pqg7h is Pending 0/1, web container waiting in ErrImagePull: failed to resolve reference docker.io/library/nginx:1.99.99-does-not-exist: not found
- `kubernetes_describe_deployment`: frontend has 0/1 ready replicas, Available=False (MinimumReplicasUnavailable). Revision 1 is the only ReplicaSet and uses image nginx:1.99.99-does-not-exist.

**Recommendations**
1. Set the frontend deployment image to a valid nginx tag that exists on Docker Hub, for example kubectl set image deployment/frontend web=nginx:<valid-tag> -n demo.
2. Fix the image tag in the source manifest or CI pipeline so the bad tag isn't redeployed.
3. Check that the pod becomes Ready and the deployment reaches 1/1 available.
4. Frontend has no working revision, so it is serving no traffic. Treat it as a full outage for this service.
5. The checkout (crashing, exit 1) and reports (OOMKilled) pods in demo are also unhealthy. They look like separate issues and need their own triage.

Runbook: `image-pull`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_deployment`
