**oncall@example.com** deployed revision **checkout-00002-nt5** using gcloud 589.0.0. It was created on **2026-10-18 at 22:22:38 UTC** and was serving by **22:24:18 UTC**, when Cloud Run reported "Deploying revision succeeded in 1m40.46s". This revision is the one returning the 503s.

**Likely cause:** this deploy set `UPSTREAM_TIMEOUT_MS=1`. With that setting the service gives the inventory call only 1 ms, when the code's default is 2000 ms. So the call times out and the request gets a 503. The revision's logs match: `inventory lookup failed after 1 ms: URLError: <urlopen error timed out>` (timeout_ms=1), followed by HTTP 503 responses, for example at 22:34:23–22:34:31 UTC.

The deploy record came from the Cloud Run `system_event` audit log, which names oncall@example.com as creator and last modifier of the service. My filters seemed to be ignored and both queries returned the same mixed results, so I couldn't separately pull the matching `activity` audit entry.

**Recommended fix:** roll traffic back to the previous revision, or redeploy with a sensible `UPSTREAM_TIMEOUT_MS`, such as the 2000 ms default.

**Evidence**
- `gcp_list_log_entries`: cloudaudit system_event /Services.ReplaceService for namespaces/shop-prod-4f2a/revisions/checkout-00002-nt5: creator oncall@example.com, client gcloud 589.0.0, creationTimestamp 2026-10-18T22:22:38Z, Ready 22:24:18Z, env UPSTREAM_TIMEOUT_MS=1; service checkout lastModifier oncall@example.com
- `gcp_list_log_entries`: checkout-00002-nt5 logs: 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' with HTTP 503 responses around 2026-10-18T22:34:23–22:34:31Z

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND protoPayload.resourceName:\"checkout\"", "orderBy": "timestamp desc", "pageSize": 10}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND httpRequest.status=503", "orderBy": "timestamp asc", "pageSize": 5}
3. `read_more` {"result_id": "r246e4e", "grep": "cloudaudit"}
