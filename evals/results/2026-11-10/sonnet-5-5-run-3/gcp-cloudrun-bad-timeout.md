## Cloud Run service checkout is returning 503s. Its inventory lookup fails because the call uses a 1 ms timeout. The errors come from revision checkout-00002-nt5, deployed at 22:22 UTC.

**Root cause** (medium confidence, `bad_rollout`): Revision checkout-00002-nt5 was created by a ReplaceService call from oncall@example.com at 2026-10-18T22:22:37Z, replacing checkout-00001-ldp. Every error log on this revision reads "inventory lookup failed after 1 ms: URLError: <urlopen error timed out>" with timeout_ms=1, upstream=inventory. Each such failure is paired with an HTTP 503 on GET / returned in about 25 ms. A 1 ms upstream timeout is far too short for any network call, so every request fails. The timeout value most likely came from a config or env change in the new revision. The audit log request payload I saw did not show env vars, so that link is inferred. I did not check the inventory service's own health, and I did not confirm that the first revision had no errors.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/cloud_run_service/checkout, shop-prod-4f2a/cloud_run_revision/checkout-00002-nt5

**Evidence**
- `gcp_list_log_entries`: Error logs on revision checkout-00002-nt5 repeat "inventory lookup failed after 1 ms: URLError: <urlopen error timed out>" with timeout_ms: 1, upstream: inventory. Matching request logs show status 503 with about 25 ms latency, at 22:34:23-22:34:31Z.
- `gcp_list_log_entries`: Audit log shows google.cloud.run.v1.Services.ReplaceService on services/checkout by oncall@example.com at 22:22:37Z. It produced revision checkout-00002-nt5. The service was created at 22:17 with revision checkout-00001-ldp, which was Ready.

**Recommendations**
1. Roll back: route 100% of traffic to checkout-00001-ldp (gcloud run services update-traffic checkout --to-revisions=checkout-00001-ldp=100 --region us-central1).
2. Inspect revision checkout-00002-nt5 (gcloud run revisions describe) for the inventory timeout env var or config. Set it to a sensible value such as 1-5 s rather than 1 ms.
3. Confirm the inventory service itself is healthy by checking its logs and latency, so the failure is not hidden behind the bad timeout.
4. After the rollback, confirm the 5xx rate drops. Add a config validation or canary step for timeout settings in future rollouts.

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "severity>=ERROR AND resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\"", "orderBy": "timestamp desc", "pageSize": 15}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\"", "orderBy": "timestamp desc", "pageSize": 15}
3. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND protoPayload.methodName:\"Services\"", "orderBy": "timestamp desc", "pageSize": 5}
4. `read_more` {"result_id": "r4914b6", "grep": "cloudaudit", "fields": "timestamp,protoPayload.methodName,protoPayload.resourceName,protoPayload.authenticationInfo.principalEmail,protoPayload.request"} (error)
5. `read_more` {"result_id": "r4914b6", "grep": "cloudaudit", "fields": ["timestamp", "protoPayload.methodName", "protoPayload.resourceName", "protoPayload.authenticationInfo.principalEmail", "protoPayload.request"]}
