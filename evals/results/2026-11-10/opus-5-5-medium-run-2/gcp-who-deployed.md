**oncall@example.com** deployed it on **2026-10-18 at 22:22:37 UTC**, using gcloud 589.0.0.

- **What happened:** The audit log shows `google.cloud.run.v1.Services.ReplaceService` run on `services/checkout`. This created revision **checkout-00002-nt5**. The revision was created at 22:22:38Z and became Ready at 22:24:18Z ("Deploying revision succeeded in 1m40.46s"). Its creator and the service's last modifier are both oncall@example.com.
- **Which revision returns the 503s:** All the 503s I found came from checkout-00002-nt5. Each one comes with the app log line `inventory lookup failed after 1 ms: URLError: <urlopen error timed out>`. I didn't confirm the exact time the first 503 appeared, but every one I saw is on this revision.
- **Likely cause:** The new revision sets env `UPSTREAM_TIMEOUT_MS=1`. The previous revision, checkout-00001-ldp (created by the same user at 22:17:04Z), started with `inventory timeout 2000 ms`. With a 1 ms timeout, every inventory call times out and the request returns 503 `inventory unavailable`.

**Recommendation:** Set `UPSTREAM_TIMEOUT_MS` back to 2000, or route traffic back to checkout-00001-ldp. I can only read, so someone with deploy rights needs to make that change.

**Evidence**
- `gcp_list_log_entries`: Activity audit log: 2026-10-18T22:22:37.931973Z google.cloud.run.v1.Services.ReplaceService on namespaces/shop-prod-4f2a/services/checkout by principalEmail oncall@example.com (earlier CreateService 22:17:04Z by the same user)
- `gcp_list_log_entries`: System_event audit: revision checkout-00002-nt5 created 2026-10-18T22:22:38Z, serving.knative.dev/creator oncall@example.com, gcloud 589.0.0, env UPSTREAM_TIMEOUT_MS="1", Ready at 22:24:18Z
- `gcp_list_log_entries`: checkout 503 responses (e.g. 22:34:30Z) all on revision checkout-00002-nt5, with stdout ERROR 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>', timeout_ms=1
- `gcp_list_log_entries`: Prior revision checkout-00001-ldp logged 'checkout listening, inventory timeout 2000 ms' at 22:17:15Z

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND httpRequest.status=503", "orderBy": "timestamp desc", "pageSize": 10}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND resource.type=\"cloud_run_revision\" OR (logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND protoPayload.serviceName=\"run.google
3. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND timestamp<=\"2026-10-18T22:35:00Z\"", "orderBy": "timestamp desc", "pageSize": 15}
4. `read_more` {"result_id": "ra99ea8", "grep": "cloudaudit"}
5. `read_more` {"result_id": "ra99ea8", "grep": "principalEmail", "fields": ["timestamp", "logName", "protoPayload.methodName", "protoPayload.resourceName", "protoPayload.authenticationInfo.principalEmail"]}
6. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND httpRequest.status=503 AND timestamp>=\"2026-10-18T22:00:00Z\"", "orderBy": "timestamp asc", "pageSize": 3}
7. `read_more` {"result_id": "r0afb5b", "grep": "checkout-00001", "fields": ["timestamp", "logName", "httpRequest.status", "jsonPayload.message", "resource.labels.revision_name"]}
