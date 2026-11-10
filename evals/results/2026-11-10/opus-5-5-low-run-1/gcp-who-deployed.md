**oncall@example.com** deployed the failing revision **checkout-00002-nt5** with gcloud 589.0.0 on **2026-10-18**. The revision was created at **22:22:38 UTC** and became Ready and started taking traffic at **22:24:18 UTC**. The same operation (id 9bcbd8df-…) changed the `checkout` service to generation 2, and the service's `lastModifier` is also oncall@example.com.

**What caused the 503s:** this revision sets the environment variable `UPSTREAM_TIMEOUT_MS=1`. The code defaults to 2000 ms when the variable isn't set. With a 1 ms limit, every call to inventory times out and checkout returns 503 `inventory unavailable`. The logs from checkout-00002-nt5 show this over and over: `inventory lookup failed after 1 ms: URLError: timed out`, followed by `status: 503`. The latest entries I saw were around 22:34 UTC.

**How sure this is:** the deployer comes from the revision's `serving.knative.dev/creator` field in the Cloud Run audit log. My log filter seemed to return mixed results, so I didn't read the Admin Activity entry's `principalEmail` directly.

**Suggested fix (I can't make changes):** send traffic back to the previous revision, checkout-00001, or redeploy with a realistic `UPSTREAM_TIMEOUT_MS` such as 2000.

**Evidence**
- `gcp_list_log_entries`: Cloud Run audit entry for revisions/checkout-00002-nt5: creator oncall@example.com, client gcloud 589.0.0, created 2026-10-18T22:22:38Z, Ready 22:24:18Z, env UPSTREAM_TIMEOUT_MS=1
- `gcp_list_log_entries`: Audit entry for services/checkout generation 2: lastModifier oncall@example.com, same operation-id 9bcbd8df-0fc8-416f-a0cf-6e15aa5e74bd
- `gcp_list_log_entries`: checkout-00002-nt5 logs at ~22:34Z: 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' paired with HTTP 503 responses

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND protoPayload.resourceName:\"checkout\"", "orderBy": "timestamp desc", "pageSize": 10}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND httpRequest.status=503", "orderBy": "timestamp asc", "pageSize": 5}
3. `read_more` {"result_id": "r825005", "grep": "cloudaudit"}
