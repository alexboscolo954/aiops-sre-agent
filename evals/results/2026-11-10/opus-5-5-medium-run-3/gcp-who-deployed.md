**oncall@example.com** deployed it. On **2026-10-18 at 22:22:37 UTC** they ran `google.cloud.run.v1.Services.ReplaceService` on service `checkout` in us-central1, using gcloud 589.0.0. That deploy created revision **`checkout-00002-nt5`**, which was ready and serving at **22:24:18 UTC**. This revision is the one returning the 503s.

**Likely cause:** the deploy set the environment variable `UPSTREAM_TIMEOUT_MS=1` (the code's default is 2000). With a 1 ms limit, every inventory lookup times out. Each request then logs `inventory lookup failed after 1 ms: URLError: <urlopen error timed out>` and returns 503 `inventory unavailable`.

The same account created the service at 22:17:04 UTC and set its IAM policy at 22:17:08. I didn't pin down exactly when the first 503 happened; the samples I pulled run up to 22:34:31 and all come from `checkout-00002-nt5`.

**Suggested fix (I haven't changed anything):** set `UPSTREAM_TIMEOUT_MS` back to a sensible value such as 2000. Or, if revision `checkout-00001` was healthy, send traffic back to it.

**Evidence**
- `gcp_list_log_entries`: Activity audit log: 2026-10-18T22:22:37.931973Z google.cloud.run.v1.Services.ReplaceService on namespaces/shop-prod-4f2a/services/checkout by principalEmail oncall@example.com (earlier CreateService at 22:17:04Z and SetIamPolicy at 22:17:08Z by the same account)
- `gcp_list_log_entries`: System-event audit: revision checkout-00002-nt5 has creator oncall@example.com, gcloud 589.0.0, env UPSTREAM_TIMEOUT_MS="1", created 22:22:38Z, Ready 'Deploying revision succeeded in 1m40.46s' at 22:24:18Z
- `gcp_list_log_entries`: checkout request logs show HTTP 503s on revision checkout-00002-nt5 (e.g. 22:34:30Z), each paired with ERROR 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>', timeout_ms=1

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND httpRequest.status=503", "orderBy": "timestamp desc", "pageSize": 10}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND protoPayload.resourceName:\"checkout\"", "orderBy": "timestamp desc", "pageSize": 10}
3. `read_more` {"result_id": "rf1b599", "grep": "cloudaudit"}
4. `read_more` {"result_id": "rf1b599", "grep": "activity", "fields": ["timestamp", "protoPayload.methodName", "protoPayload.resourceName", "protoPayload.authenticationInfo.principalEmail", "logName"]}
