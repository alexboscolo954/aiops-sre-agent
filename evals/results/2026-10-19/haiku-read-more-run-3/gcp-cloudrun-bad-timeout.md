## Cloud Run service checkout is returning 503s for most requests since about 22:24 UTC on 2026-10-18. Every failure comes from revision checkout-00002-nt5, which logs inventory lookups failing after a 1 ms timeout. The previous revision, checkout-00001-ldp, logged a 2000 ms timeout and no such failures, and checkout-00002-nt5 was deployed by oncall@example.com minutes before the errors began.

**Root cause** (high confidence, `bad_rollout`): A config change in the new revision checkout-00002-nt5 made the inventory call time out almost immediately. Revision checkout-00001-ldp logged timeout_ms 2000 at 22:17:15 with no inventory errors. Revision checkout-00002-nt5 logs timeout_ms 1 on every inventory failure, from 22:24:09 onward, with messages like 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>'. The service was replaced by oncall@example.com at 22:22:37, and the revision ReplaceService calls ran at 22:22:38 and 22:24:16-22:24:18, matching the onset. The error log entries show the 1 ms timeout, and the timing points to the deploy as the cause. The exact config field was not read directly, so the cause is inferred from the logged timeout value and the timing.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/Service/checkout, shop-prod-4f2a/Revision/checkout-00002-nt5

**Evidence**
- `gcp_list_log_entries`: Severity>=ERROR logs for cloud_run_revision service checkout show only revision checkout-00002-nt5. Entries include HTTP 503 responses on GET / and stdout 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' with jsonPayload.timeout_ms 1, from 22:34:21 to 22:34:31.
- `gcp_list_log_entries`: Older revision checkout-00001-ldp logged an inventory event with timeout_ms 2000 at 22:17:15.379888, with no failures attributed to it.
- `gcp_list_log_entries`: The first logged inventory timeout_ms 1 failure on checkout-00002-nt5 is at 22:24:09.183013, shortly after the 22:22-22:24 deploy activity.
- `gcp_list_log_entries`: Cloud Audit activity log: google.cloud.run.v1.Services.ReplaceService on services/checkout by oncall@example.com at 22:22:37.931973. ReplaceService on revisions/checkout-00002-nt5 at 22:22:38, 22:24:16 and 22:24:18, and on services/checkout at 22:24:18.532. Earlier CreateService for checkout-00001-ldp at 22:17:04 and SetIamPolicy at 22:17:08.

**Recommendations**
1. Roll traffic back to the last good revision checkout-00001-ldp, for example with gcloud run services update-traffic checkout --to-revisions=checkout-00001-ldp=100 in us-central1. This needs human approval before it runs.
2. Confirm the bad setting in checkout-00002-nt5 by comparing its environment variables and timeout configuration with checkout-00001-ldp. The inventory timeout went from 2000 ms to 1 ms.
3. Fix the timeout value, redeploy as a new revision, and canary it before shifting full traffic.
4. Check the audit trail for what changed in the 22:22 ReplaceService call and who approved it, then add a deploy guard or validation for timeout values.
5. Once traffic is back on the good revision, confirm the 5xx rate in the request metrics drops and that no more inventory timeout_ms 1 errors are logged.

**Tool calls**
1. `gcp_list_log_entries` {"filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND severity>=ERROR", "orderBy": "timestamp desc", "pageSize": 20, "pageToken": "", "projectIds": ["shop-prod-4f2a"], "resourceNames": ["projects/shop-prod-4f2a"]}
2. `gcp_list_log_entries` {"filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND resource.labels.service_name=\"checkout\"", "orderBy": "timestamp desc", "pageSize": 10, "pageToken": "", "projectIds": ["shop-prod-4f2a"], "resourceNames": ["projects/shop-prod-4f2a"]}
3. `read_more` {"result_id": "r297866", "start": 0, "grep": "methodName|timeout|TIMEOUT|resourceName", "fields": ["protoPayload.methodName", "protoPayload.resourceName", "timestamp", "protoPayload.authenticationInfo.principalEmail", "jsonPayload.message"]}
4. `read_more` {"result_id": "r5e09c0", "start": 0, "grep": "inventory", "fields": ["timestamp", "jsonPayload.timeout_ms", "resource.labels.revision_name"]}
5. `read_more` {"result_id": "r297866", "start": 0, "grep": "protoPayload", "fields": ["timestamp", "protoPayload.methodName", "protoPayload.resourceName", "protoPayload.authenticationInfo"]}
6. `gcp_list_log_entries` {"filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND protoPayload.resourceName:\"checkout\" AND timestamp>=\"2026-10-18T21:30:00Z\"", "orderBy": "timestamp desc", "pageSize": 10, "pageToken": "", "projectIds": ["shop-prod-4f2a"], "resourceNames": ["projects/s
