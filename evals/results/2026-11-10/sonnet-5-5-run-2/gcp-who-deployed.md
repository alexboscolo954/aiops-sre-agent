**oncall@example.com** deployed the failing revision, `checkout-00002-nt5`, at about **2026-10-18 22:22:38 UTC**.

- The audit log shows a `Services.ReplaceService` call on `services/checkout` by `user:oncall@example.com` at 22:22:37.9Z. The revision was created at 22:22:38Z with the creator annotation `oncall@example.com`.
- The deploy used gcloud 589.0.0. The revision reported Ready at 22:24:18Z ("Deploying revision succeeded in 1m40.46s").
- oncall@example.com also created the service at 22:17:04Z (`CreateService`) and ran `SetIamPolicy` at 22:17:08Z.
- Every 503 I saw came from `checkout-00002-nt5`. Each one is paired with the log line `inventory lookup failed after 1 ms: URLError: <urlopen error timed out>`.
- The likely cause is in that deploy. The revision spec sets env `UPSTREAM_TIMEOUT_MS=1`, a 1 ms upstream timeout. The code's default is 2000 ms, so the setting looks like a misconfiguration. I recommend redeploying with a sane value, for example 2000, or rolling traffic back to the previous revision.

Caveats: the log queries returned the same latest-first results regardless of my filters, so I couldn't pull the first 503 directly. The 503s I saw run from 22:34:23Z to 22:34:31Z. Revision 00002 became ready at 22:24:18Z, and it is the only revision serving 503s in those results. I didn't verify the exact time the first 503 appeared.

**Evidence**
- `gcp_list_log_entries`: Audit activity log (via read_more on the result): google.cloud.run.v1.Services.ReplaceService on namespaces/shop-prod-4f2a/services/checkout at 2026-10-18T22:22:37.93Z, principalEmail oncall@example.com. Also CreateService at 22:17:04Z and SetIamPolicy at 22:17:08Z by the same user.
- `gcp_list_log_entries`: Revision checkout-00002-nt5 created 2026-10-18T22:22:38Z, creator oncall@example.com, client gcloud 589.0.0, Ready at 22:24:18Z; env UPSTREAM_TIMEOUT_MS=1 (code default is 2000).
- `gcp_list_log_entries`: Request logs with httpRequest.status=503 on revision checkout-00002-nt5 (22:34:23Z to 22:34:31Z), paired with stdout errors 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' (timeout_ms 1).

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND resource.type=\"cloud_run_revision\" OR (logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND protoPayload.serviceName=\"run.google
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND httpRequest.status=503", "orderBy": "timestamp desc", "pageSize": 5}
3. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND protoPayload.serviceName=\"run.googleapis.com\"", "orderBy": "timestamp desc", "pageSize": 10}
4. `read_more` {"result_id": "ra7ff76", "grep": "cloudaudit"}
5. `read_more` {"result_id": "r3133ad", "grep": "cloudaudit"}
6. `read_more` {"result_id": "ra7ff76", "grep": "principalEmail", "fields": ["timestamp", "logName", "protoPayload.methodName", "protoPayload.resourceName", "protoPayload.authenticationInfo"]}
7. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND httpRequest.status=503 AND timestamp>=\"2026-10-18T22:00:00Z\"", "orderBy": "timestamp asc", "pageSize": 1}
8. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND timestamp>=\"2026-10-18T22:24:00Z\" AND timestamp<=\"2026-10-18T22:26:00Z\"", "orderBy": "timestamp asc", "pageSize": 3}
