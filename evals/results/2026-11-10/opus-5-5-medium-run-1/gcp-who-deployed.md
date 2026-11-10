**`oncall@example.com` deployed it on 2026-10-18 at 22:22:37 UTC.** The revision is **`checkout-00002-nt5`** (Cloud Run service `checkout`, us-central1).

- **The deploy:** at 22:22:37.93Z the admin-activity audit log records `google.cloud.run.v1.Services.ReplaceService` on `namespaces/shop-prod-4f2a/services/checkout`, made by `user:oncall@example.com` with gcloud 589.0.0. That made the service's configuration generation 2.
- **The revision:** `checkout-00002-nt5` was created at 22:22:38Z, with creator and last modifier both `oncall@example.com`. It finished rolling out (Ready=True) at 22:24:18Z.
- **Earlier activity by the same account:** it created the service (`CreateService`) at 22:17:04Z and changed its IAM policy (`SetIamPolicy`) at 22:17:08Z.

**Likely cause of the 503s:** this revision sets the env var `UPSTREAM_TIMEOUT_MS="1"`. The code's default is 2000 ms. With a 1 ms limit, every inventory lookup times out, and the handler returns 503 "inventory unavailable". The revision's logs match: `inventory lookup failed after 1 ms: URLError: <urlopen error timed out>`, followed by HTTP 503s (for example at 22:34:30Z). I only looked at the newest 503s and didn't pin down the exact first one, but they come from this revision and match its config.

**Suggested fix (I can't make changes):** send traffic back to the previous revision, or redeploy with `UPSTREAM_TIMEOUT_MS` restored to a sane value such as 2000. Check with oncall@example.com whether the value of 1 was a mistake for 1000 or meant to be in seconds.

**Evidence**
- `gcp_list_log_entries`: cloudaudit activity log: 2026-10-18T22:22:37.931973Z google.cloud.run.v1.Services.ReplaceService on namespaces/shop-prod-4f2a/services/checkout, principalEmail oncall@example.com (also CreateService 22:17:04Z and SetIamPolicy 22:17:08Z by the same user)
- `gcp_list_log_entries`: cloudaudit system_event: revision checkout-00002-nt5 created 22:22:38Z, serving.knative.dev/creator oncall@example.com, env UPSTREAM_TIMEOUT_MS="1", Ready 'Deploying revision succeeded in 1m40.46s' at 22:24:18Z
- `gcp_list_log_entries`: checkout-00002-nt5 request logs show status 503 (e.g. 22:34:30Z) with stdout ERROR 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>', timeout_ms=1

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name:\"checkout\" AND httpRequest.status=503", "orderBy": "timestamp desc", "pageSize": 10}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND protoPayload.resourceName:\"checkout\"", "orderBy": "timestamp desc", "pageSize": 20}
3. `read_more` {"result_id": "ra97346", "grep": "cloudaudit"}
4. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND timestamp>=\"2026-10-18T22:00:00Z\" AND timestamp<=\"2026-10-18T22:40:00Z\"", "orderBy": "timestamp desc", "pageSize": 10}
5. `read_more` {"result_id": "rb6a6a8", "grep": "principalEmail", "fields": ["timestamp", "logName", "protoPayload.methodName", "protoPayload.resourceName", "protoPayload.authenticationInfo", "protoPayload.request.spec.template.spec.containers"]}
