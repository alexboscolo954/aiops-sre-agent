**oncall@example.com deployed it at 2026-10-18 22:22:37 UTC.** The revision is **checkout-00002-nt5** (service `checkout`, us-central1, project shop-prod-4f2a).

- **Who and how:** The Admin Activity audit log has a `google.cloud.run.v1.Services.ReplaceService` call on `namespaces/shop-prod-4f2a/services/checkout`, made by `oncall@example.com` with gcloud 589.0.0. That user also created the service at 22:17:04 UTC.
- **When it went live:** The revision was created at 22:22:38 UTC. It became Ready and started serving at 22:24:18 UTC ("Deploying revision succeeded in 1m40.46s"). The revision's `serving.knative.dev/creator` is also oncall@example.com.
- **Why it returns 503s (very likely):** This deploy set the environment variable `UPSTREAM_TIMEOUT_MS=1`. The code defaults to 2000 when the variable isn't set. With a 1 ms limit, every inventory lookup times out and checkout answers 503 "inventory unavailable". The checkout-00002-nt5 logs show this repeatedly: `inventory lookup failed after 1 ms: URLError: <urlopen error timed out>` with `timeout_ms: 1`, each paired with a 503 GET in about 25 ms.

One gap: I couldn't pin down exactly when the 503s started. The log tool gave back the same entries (around 22:34 UTC) no matter which time range or sort order I asked for. So I can show the errors come from this revision, but not the exact minute they began.

Suggested fix (I only have read access, so this is for you to do): send traffic back to the previous revision, or redeploy with `UPSTREAM_TIMEOUT_MS` removed or set to something sensible like 2000. Then check with oncall@example.com whether the 1 ms value was a typo, for example meant to be 1000.

**Evidence**
- `gcp_list_log_entries`: cloudaudit activity log: 2026-10-18T22:22:37.931973Z google.cloud.run.v1.Services.ReplaceService on namespaces/shop-prod-4f2a/services/checkout by principalEmail oncall@example.com (earlier CreateService 22:17:04Z by the same user)
- `gcp_list_log_entries`: cloudaudit system_event: revision checkout-00002-nt5 creationTimestamp 2026-10-18T22:22:38Z, creator oncall@example.com, env UPSTREAM_TIMEOUT_MS="1" (code default 2000), Ready 'Deploying revision succeeded in 1m40.46s' at 22:24:18Z
- `gcp_list_log_entries`: checkout-00002-nt5 request logs: GET / status 503 (~25ms latency) paired with stdout ERROR 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>', timeout_ms=1, around 2026-10-18T22:34Z

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name:\"checkout\" AND httpRequest.status=503", "orderBy": "timestamp desc", "pageSize": 10}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND protoPayload.resourceName:\"checkout\"", "orderBy": "timestamp desc", "pageSize": 20}
3. `read_more` {"result_id": "r561837", "grep": "cloudaudit"}
4. `read_more` {"result_id": "r561837", "grep": "principalEmail", "fields": ["timestamp", "logName", "protoPayload.methodName", "protoPayload.resourceName", "protoPayload.authenticationInfo.principalEmail", "protoPayload.request.spec.template.spec.containers"]}
5. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND httpRequest.status=503 AND timestamp>=\"2026-10-18T22:00:00Z\"", "orderBy": "timestamp asc", "pageSize": 3}
