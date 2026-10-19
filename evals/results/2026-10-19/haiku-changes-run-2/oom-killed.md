## The reports pod is crash looping because its app container is OOMKilled (exit 137) at a 48Mi memory limit while it loads a 200MB dataset. The limit is far below the workload's needs, so this looks like a resource limit problem, not a code regression. Separately, a checkout rollout (revision 2) removed DATABASE_URL and is also crashing, but that is a different workload and not the cause of this alert.

**Root cause** (medium confidence, `resource_limits`): The reports deployment (revision 1, python:3.12-alpine) has memory limit 48Mi and request 32Mi. Its log shows it loading 200MB of rows into memory before the kernel OOM-kills it. The limit is too small for the job it runs, and the deployment has no earlier revision to roll back to.
**Severity:** high  ·  **Affected:** demo/Deployment/reports, demo/Pod/reports-55b4fffc66-hmq7f

**Evidence**
- `kubernetes_list_pods`: reports-55b4fffc66-hmq7f: Running, 0/1 ready, 3 restarts, last terminated OOMKilled exit 137.
- `kubernetes_describe_pod`: Container app: image python:3.12-alpine, requests memory 32Mi, limits memory 48Mi, state OOMKilled exit 137, restarts 3.
- `kubernetes_pod_logs (previous=true, container app)`: Previous instance logs are gone. Latest instance shows 'building monthly report: loading 200MB of rows' before the kill.
- `kubernetes_describe_deployment`: reports has 1 revision only (created 2m ago). Available=False, MinimumReplicasUnavailable. Image and limits unchanged since creation.
- `kubernetes_recent_changes`: Only recent rollouts: checkout revision 2 (env DATABASE_URL removed, 48s ago) and new revision 1 creations for checkout, frontend and reports. No reports rollout changed the memory limit.
- `runbooks_runbook_for_alert (KubePodCrashLooping)`: Matched pod-crashlooping and oom-killed runbooks. OOMKilled points to the oom-killed runbook: a limit that is too small for a healthy workload is fixed by raising it, not by restarting.

**Recommendations**
1. Raise the reports container memory limit (and request) above the observed peak. Loading 200MB of rows needs well over 48Mi, so start around 256Mi and tune from observed usage. This needs human approval since it changes the deployment.
2. Alternatively, change the job to stream rows instead of loading all 200MB at once, if the code can be changed.
3. Do not restart the pod; a restart will not fix the OOM loop.
4. Separately, investigate the checkout deployment: revision 2 removed the DATABASE_URL env var, which is the likely cause of its Error crash loop. Restore the variable or roll back to revision 1 (this is a different alert).
5. The frontend pod is in ErrImagePull because its image tag nginx:1.99.99-does-not-exist does not exist. Fix the tag (separate issue).

Runbook: `oom-killed`

**Tool calls**
1. `runbooks_runbook_for_alert`
2. `kubernetes_list_pods`
3. `kubernetes_describe_pod`
4. `kubernetes_describe_deployment`
5. `kubernetes_recent_changes`
6. `kubernetes_pod_logs`
