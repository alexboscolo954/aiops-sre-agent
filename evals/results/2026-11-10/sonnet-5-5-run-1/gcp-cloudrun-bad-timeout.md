## Cloud Run service checkout returns 503s on revision checkout-00002-nt5, which was deployed at 22:22 UTC. Every failing request logs an inventory lookup that times out after 1 ms.

**Root cause** (medium confidence, `bad_rollout`): A new revision, checkout-00002-nt5, was deployed by oncall@example.com via ReplaceService at 2026-10-18T22:22:37Z. Since then the service logs 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' with timeout_ms=1 and upstream=inventory, and each failing request returns 503 in about 25 ms. A 1 ms upstream timeout cannot succeed in practice, so this looks like a timeout setting changed or introduced in the new revision. I did not see the revision's env or config diff. I also did not see the 5xx rate from before the deploy or the logs of checkout-00001-ldp, because my log filters were not honoured and returned only the newest errors, which are all from revision 00002. The inventory service itself was not checked.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/cloud_run_service/checkout, us-central1/cloud_run_revision/checkout-00002-nt5

**Evidence**
- `gcp_list_log_entries`: Error logs on revision checkout-00002-nt5 from 22:34:23 to 22:34:31 repeat 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' with timeout_ms=1 and upstream=inventory. Each is paired with a 503 request log of about 25 ms latency.
- `gcp_list_log_entries`: Audit log: oncall@example.com ran google.cloud.run.v1.Services.ReplaceService on services/checkout at 22:22:37Z. Revision checkout-00002-nt5 was then created and the service was updated again by 22:24:18Z. The service was first created at 22:17:04Z as checkout-00001-ldp, so the rollout comes shortly before the errors.

**Recommendations**
1. Roll back: route 100% of traffic to checkout-00001-ldp with `gcloud run services update-traffic checkout --to-revisions=checkout-00001-ldp=100 --region us-central1`.
2. Compare the env vars and config of checkout-00002-nt5 against checkout-00001-ldp, and find where the inventory timeout is set to 1 ms. The audit request I read did not show the env vars.
3. Redeploy with a sensible inventory timeout, for example hundreds of ms to seconds, and add a retry.
4. Check that the inventory service is healthy.
5. Add a canary or gradual traffic split for future checkout revisions.

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "severity>=ERROR AND resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\"", "orderBy": "timestamp desc", "pageSize": 20}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND protoPayload.resourceName:\"checkout\"", "orderBy": "timestamp desc", "pageSize": 10}
3. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND timestamp>=\"2026-10-18T00:00:00Z\"", "orderBy": "timestamp desc", "pageSize": 10}
4. `read_more` {"result_id": "r9bde36", "grep": "methodName", "fields": "timestamp,protoPayload.methodName,protoPayload.authenticationInfo.principalEmail,protoPayload.resourceName,protoPayload.request,protoPayload.response.spec"} (error)
5. `read_more` {"result_id": "r9bde36", "grep": "methodName", "fields": ["timestamp", "protoPayload.methodName", "protoPayload.authenticationInfo.principalEmail", "protoPayload.resourceName", "protoPayload.request"]}
6. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.revision_name=\"checkout-00001-ldp\" AND timestamp>=\"2026-10-18T22:17:00Z\"", "orderBy": "timestamp desc", "pageSize": 3}
