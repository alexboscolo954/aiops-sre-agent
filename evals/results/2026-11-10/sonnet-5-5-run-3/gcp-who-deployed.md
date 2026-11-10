**oncall@example.com** deployed the failing revision, **checkout-00002-nt5**, at **2026-10-18 22:22:37 UTC**. The audit log records this as a `google.cloud.run.v1.Services.ReplaceService` call on `namespaces/shop-prod-4f2a/services/checkout`.

Revision 00002 became ready within about a second, and the first 503 I saw came about 12 minutes later.

- **Earlier history:** the same principal created the service and revision `checkout-00001-ldp` at about 22:17:05 UTC and set its IAM policy at 22:17:08.
- **503s:** every 503 I retrieved came from `checkout-00002-nt5`, and the earliest was at 22:34:21 UTC. The log query returned only the newest page of results. I could not confirm whether any 503 occurred between 22:22 and 22:34, so the exact onset is unverified.
- **Likely cause:** each 503 is paired with the log `inventory lookup failed after 1 ms: URLError: <urlopen error timed out>` (`timeout_ms: 1`, `upstream: inventory`). That points to the inventory call timeout being set to 1 ms in this revision. I did not look at the revision's configuration, so I can't confirm the setting.

Recommended action: roll back to `checkout-00001-ldp`, or deploy a revision with a sane inventory timeout.

**Evidence**
- `gcp_list_log_entries`: Audit activity log at 2026-10-18T22:22:37.931973Z: google.cloud.run.v1.Services.ReplaceService on namespaces/shop-prod-4f2a/services/checkout, principalEmail oncall@example.com. Earlier, CreateService at 22:17:04 and SetIamPolicy at 22:17:08 were by the same principal. System events show revision checkout-00002-nt5 created from 22:22:38.
- `gcp_list_log_entries`: HTTP 503s on checkout (the five returned, 22:34:21–22:34:31 UTC) were all from revision checkout-00002-nt5, with paired stdout errors 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' (timeout_ms 1, upstream inventory).

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND protoPayload.resourceName:\"checkout\" AND protoPayload.methodName:\"Services\"", "orderBy": "timestamp desc", "pageSize": 10}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND httpRequest.status=503", "orderBy": "timestamp desc", "pageSize": 5}
3. `read_more` {"result_id": "rbd8b39", "grep": "cloudaudit", "fields": "timestamp,protoPayload.methodName,protoPayload.resourceName,protoPayload.authenticationInfo.principalEmail,logName"} (error)
4. `read_more` {"result_id": "rbd8b39", "grep": "cloudaudit", "fields": ["timestamp", "protoPayload.methodName", "protoPayload.resourceName", "protoPayload.authenticationInfo.principalEmail", "logName"]}
5. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND httpRequest.status=503 AND timestamp>=\"2026-10-18T22:00:00Z\"", "orderBy": "timestamp asc", "pageSize": 1}
6. `read_more` {"result_id": "rf5b08a", "grep": "checkout-00001", "fields": ["timestamp", "resource.labels.revision_name", "httpRequest.status"]}
7. `read_more` {"result_id": "rf5b08a", "grep": "\"status\": 503", "fields": ["timestamp", "resource.labels.revision_name"]}
8. `read_more` {"result_id": "rf5b08a", "grep": "checkout-00002-nt5", "fields": ["timestamp", "httpRequest.status"], "start": 0}
9. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND httpRequest.status=503 AND timestamp>=\"2026-10-18T22:00:00Z\" AND timestamp<=\"2026-10-18T22:34:21Z\"", "orderBy": "timestamp asc", "pageSize": 3}
10. `read_more` {"result_id": "rd5cff2", "grep": "\"status\": 503", "fields": ["timestamp", "resource.labels.revision_name"]}
