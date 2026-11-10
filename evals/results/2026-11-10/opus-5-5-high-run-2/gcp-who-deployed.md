**oncall@example.com** deployed it at **2026-10-18 22:22:37 UTC**. They ran `gcloud` (client 589.0.0), which called `google.cloud.run.v1.Services.ReplaceService` on service `checkout` (us-central1). That created revision **`checkout-00002-nt5`**, which was serving traffic by 22:24:18 UTC. Every 503 I found comes from that revision.

**What changed in the deploy:** it set the env var `UPSTREAM_TIMEOUT_MS=1`, so the call to inventory times out after 1 ms. The container started at 22:24:09 logging `checkout listening, inventory timeout 1 ms`. The previous revision `checkout-00001`, created by the same user at 22:17, logged `inventory timeout 2000 ms`. Each failing request now logs `inventory lookup failed after 1 ms: URLError: <urlopen error timed out>` and returns 503 `inventory unavailable`.

**Timeline:** the earliest 503 I saw was 22:34:21 UTC, and they were still happening at 22:34:31. My log queries returned a limited window, so the 503s may have started earlier than 22:34:21.

**Suggested fix:** move traffic back to `checkout-00001`, or redeploy with `UPSTREAM_TIMEOUT_MS` at 2000 (the earlier value) or removed. I can only read, so I haven't changed anything.

**Evidence**
- `gcp_list_log_entries`: cloudaudit activity log: 2026-10-18T22:22:37.931973Z google.cloud.run.v1.Services.ReplaceService on namespaces/shop-prod-4f2a/services/checkout, principalEmail oncall@example.com (also created the service via CreateService at 22:17:04)
- `gcp_list_log_entries`: system_event log: revision checkout-00002-nt5 created 22:22:38 by oncall@example.com (gcloud 589.0.0), env UPSTREAM_TIMEOUT_MS="1", Ready 'Deploying revision succeeded' at 22:24:18Z
- `gcp_list_log_entries`: checkout-00002-nt5 stdout at 22:24:09: 'checkout listening, inventory timeout 1 ms'; checkout-00001 at 22:17:15: 'checkout listening, inventory timeout 2000 ms'
- `gcp_list_log_entries`: run.googleapis.com/requests: 503s on revision checkout-00002-nt5 from 22:34:21 to 22:34:31, each followed by 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>'

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND httpRequest.status=503", "orderBy": "timestamp desc", "pageSize": 10}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND protoPayload.resourceName:\"checkout\"", "orderBy": "timestamp desc", "pageSize": 10}
3. `read_more` {"result_id": "r025c38", "grep": "cloudaudit"}
4. `read_more` {"result_id": "r025c38", "grep": "principalEmail", "fields": ["timestamp", "logName", "protoPayload.methodName", "protoPayload.resourceName", "protoPayload.authenticationInfo", "protoPayload.request.spec.template.spec.containers"]}
5. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND httpRequest.status=503 AND timestamp>=\"2026-10-18T22:00:00Z\"", "orderBy": "timestamp asc", "pageSize": 3}
6. `read_more` {"result_id": "r6254ed", "grep": "checkout-00001", "fields": ["timestamp", "logName", "severity", "httpRequest.status", "jsonPayload.message", "protoPayload.methodName"]}
7. `read_more` {"result_id": "r6254ed", "grep": "checkout-00002", "fields": ["timestamp", "httpRequest.status", "jsonPayload.message"], "start": 8000}
8. `read_more` {"result_id": "r6254ed", "grep": "checkout-00002", "fields": ["timestamp", "httpRequest.status", "jsonPayload.message"]}
