## Checkout Cloud Run service is returning 5xx on the new revision checkout-00002-nt5, which 5xx-ed for ~all traffic by 22:34 UTC. The cause is an inventory client timeout that was changed from 2000 ms to 1 ms in a config update at 22:22 UTC; every inventory call now times out immediately.

**Root cause** (high confidence, `bad_config`): Revision checkout-00002-nt5 was deployed by oncall@example.com (ReplaceService on services/checkout at 22:22:37 UTC, then several revision updates until 22:24:18). Its startup log says "checkout listening, inventory timeout 1 ms" (22:24:09), while the original revision checkout-00001-ldp logged "inventory timeout 2000 ms" (22:17:15). Every request on the new revision logs "inventory lookup failed after 1 ms: URLError: <urlopen error timed out>" and returns 503. The 1 ms timeout is far too short for a network call to inventory, so the 5xx ratio goes to nearly 100% on the new revision. Traffic has shifted from 2xx on checkout-00001-ldp to 5xx on checkout-00002-nt5 by about 22:30 UTC. The timeout value is the deciding fact; no code change is visible in the logs.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/Cloud Run service/checkout, shop-prod-4f2a/Cloud Run revision/checkout-00002-nt5

**Evidence**
- `gcp_query_range`: request_count by revision: checkout-00001-ldp 2xx went from ~48-72 req/s to 0 at 22:30-22:35 UTC; checkout-00002-nt5 5xx rose from 7 to 117 to 124 req/s over the same window.
- `gcp_list_log_entries (audit, cloudaudit activity)`: oncall@example.com called google.cloud.run.v1.Services.ReplaceService on services/checkout at 2026-10-18T22:22:37Z; revisions were updated again at 22:22:38, 22:24:16 and 22:24:18, following CreateService for checkout-00001-ldp at 22:17.
- `gcp_list_log_entries (run stdout, all severities)`: checkout-00001-ldp started with 'checkout listening, inventory timeout 2000 ms' (22:17:15Z); checkout-00002-nt5 started with 'checkout listening, inventory timeout 1 ms' (22:24:09Z).
- `gcp_list_log_entries (ERROR severity, run stdout and requests)`: checkout-00002-nt5 logs 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' repeatedly (22:34:21-22:34:31Z) and returns HTTP 503 with ~25 ms latency on GET /.

**Recommendations**
1. Roll back the checkout service to checkout-00001-ldp (2000 ms inventory timeout) by shifting 100% of traffic to that revision. This needs human approval before it is run.
2. Before redeploying, find where the inventory timeout is set (env var or config in the 00002 revision) and correct it from 1 ms to the intended value, probably 2000 ms.
3. Check that inventory itself is healthy, since the timeouts were logged as 1 ms, not as real upstream slowness.
4. Add a config review or a canary check on startup timeout values to prevent a repeat.

**Tool calls**
1. `gcp_query_range` {"name": "projects/shop-prod-4f2a", "location": "global", "query": "sum by (revision_name, response_code_class) (rate(run_googleapis_com:request_count{monitored_resource=\"cloud_run_revision\", service_name=\"checkout\"}[5m]))", "start": "now-3h", "end": "now", "step": "60s"}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND severity>=ERROR", "orderBy": "timestamp desc", "pageSize": 20}
3. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND resource.labels.service_name=\"checkout\"", "orderBy": "timestamp desc", "pageSize": 10}
4. `read_more` {"result_id": "rdc340c", "grep": "methodName", "fields": ["protoPayload.methodName", "protoPayload.resourceName", "protoPayload.authenticationInfo", "timestamp"]}
5. `read_more` {"result_id": "rb042ac", "grep": "inventory", "fields": ["jsonPayload.message", "timestamp"]}
6. `TriageReport` {"summary": "Checkout Cloud Run service is returning 5xx on the new revision checkout-00002-nt5, which 5xx-ed for ~all traffic by 22:34 UTC. The cause is an inventory client timeout that was changed from 2000 ms to 1 ms in a config update at 22:22 UTC; every inventory call now times out immediately.
