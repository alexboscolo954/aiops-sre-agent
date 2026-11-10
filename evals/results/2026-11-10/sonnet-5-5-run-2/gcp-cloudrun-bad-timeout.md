## Cloud Run service checkout is returning 503s. Every request fails because its inventory lookup times out after 1 ms. This began with revision checkout-00002-nt5, deployed at 22:22:37Z by oncall@example.com.

**Root cause** (medium confidence, `bad_rollout`): Revision checkout-00002-nt5 replaced checkout-00001-ldp via ReplaceService at 2026-10-18T22:22:37Z, and 100% of traffic went to it. Every error log from that revision reads "inventory lookup failed after 1 ms: URLError: <urlopen error timed out>" with timeout_ms=1 and upstream=inventory. A 1 ms upstream timeout cannot be met by any real network call, so each request fails and the service returns 503 with about 25 ms latency. The 1 ms value looks like a timeout setting introduced in the new revision. The audit log request payload did not show env vars, so the exact setting is inferred. I did not compare the 00001 and 00002 revision specs, and I did not check whether the inventory service itself is healthy.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/cloud_run_service/checkout, us-central1/cloud_run_revision/checkout-00002-nt5

**Evidence**
- `gcp_list_log_entries`: Cloud Run stdout ERROR logs on revision checkout-00002-nt5, repeating every few seconds up to 22:34:31Z: "inventory lookup failed after 1 ms: URLError: <urlopen error timed out>", timeout_ms=1, upstream=inventory. The paired request logs show GET / returning status 503 at about 24-28 ms latency.
- `gcp_list_log_entries`: Audit log shows google.cloud.run.v1.Services.ReplaceService on services/checkout by oncall@example.com at 22:22:37Z. It created revision checkout-00002-nt5, which succeeded the original CreateService revision checkout-00001-ldp from 22:17Z. The 503s appear only on revision 00002.

**Recommendations**
1. Roll back by routing 100% of checkout traffic to the previous revision checkout-00001-ldp, for example with gcloud run services update-traffic checkout --to-revisions=checkout-00001-ldp=100.
2. Compare the checkout-00001-ldp and checkout-00002-nt5 revision specs (env vars, timeout settings) and correct the inventory timeout from 1 ms to a sensible value, for example a few seconds, before redeploying.
3. Confirm the inventory upstream is healthy, since the 1 ms timeout would mask any real inventory problem.
4. Add a canary or gradual traffic split for future checkout deploys, and validate timeout config values in review.
5. After the rollback, confirm the 5xx rate drops and the alert resolves.

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "severity>=ERROR AND resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\"", "orderBy": "timestamp desc", "pageSize": 15}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\"", "orderBy": "timestamp desc", "pageSize": 15}
3. `read_more` {"result_id": "r33b002", "grep": "methodName", "fields": ["timestamp", "protoPayload.methodName", "protoPayload.resourceName", "protoPayload.authenticationInfo.principalEmail", "protoPayload.request"]}
4. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "protoPayload.serviceName=\"run.googleapis.com\" AND protoPayload.methodName:\"Service\"", "orderBy": "timestamp desc", "pageSize": 5}
