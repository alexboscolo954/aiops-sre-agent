**Who and when:** `oncall@example.com` deployed it at **2026-10-18 22:22:37 UTC**. They used gcloud (`google.cloud.run.v1.Services.ReplaceService` on `services/checkout`, client gcloud 589.0.0). That deploy created revision **`checkout-00002-nt5`**, which became Ready at 22:24:18 UTC ("Deploying revision succeeded in 1m40.46s"). The same person had created the service (revision `checkout-00001-ldp`) at 22:17:04 UTC.

**Why it returns 503s:** the new revision sets the environment variable `UPSTREAM_TIMEOUT_MS=1`. When that variable isn't set, the code uses 2000 ms. With a 1 ms limit, every call to the inventory service times out and the request gets a 503. The logs on `checkout-00002-nt5` show the pattern: `inventory lookup failed after 1 ms: URLError: <urlopen error timed out>` (`timeout_ms: 1`), each followed by a 503 that takes about 24 ms. In the results I pulled, every 503 came from `checkout-00002-nt5` and none from `checkout-00001-ldp`. I didn't look at metrics, so I can't say whether 00001 ever failed.

**Suggested fix** (I can only read, so I haven't changed anything): send traffic back to `checkout-00001-ldp`, or deploy again with `UPSTREAM_TIMEOUT_MS` set to a sensible value such as the 2000 ms default. It's worth checking with oncall@example.com whether the 1 ms value was a typo.

**Evidence**
- `gcp_list_log_entries`: Activity audit log: 2026-10-18T22:22:37.931973Z google.cloud.run.v1.Services.ReplaceService on namespaces/shop-prod-4f2a/services/checkout by principalEmail oncall@example.com (service created by the same user at 22:17:04Z via CreateService)
- `gcp_list_log_entries`: System-event audit log: revision checkout-00002-nt5 (creator oncall@example.com, operation 9bcbd8df…, gcloud 589.0.0) created 22:22:38Z, Ready 22:24:18Z; container env UPSTREAM_TIMEOUT_MS="1" (code default 2000)
- `gcp_list_log_entries`: Cloud Run logs for service checkout, revision checkout-00002-nt5: repeated 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' each followed by an HTTP 503 (e.g. 22:34:30Z, 22:34:28Z, 22:34:26Z)

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND httpRequest.status=503", "orderBy": "timestamp desc", "pageSize": 10}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND protoPayload.resourceName:\"checkout\"", "orderBy": "timestamp desc", "pageSize": 20}
3. `read_more` {"result_id": "rdc5980", "grep": "cloudaudit"}
4. `read_more` {"result_id": "rdc5980", "grep": "cloudaudit.googleapis.com%2Factivity", "fields": ["timestamp", "logName", "protoPayload.methodName", "protoPayload.resourceName", "protoPayload.authenticationInfo", "protoPayload.request.spec.template.spec.containers"]}
5. `read_more` {"result_id": "re257a9", "grep": "checkout-00001", "fields": ["timestamp", "httpRequest.status", "resource.labels.revision_name"]}
