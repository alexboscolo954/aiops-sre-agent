## Since 22:24 UTC, the checkout Cloud Run service has been answering requests with 503s. Revision checkout-00002-nt5, deployed by oncall@example.com at 22:22 UTC, cut the inventory call's timeout (UPSTREAM_TIMEOUT_MS) from 2000 ms to 1 ms, so the call times out on nearly every request.

**Root cause** (high confidence, `bad_rollout`): The only change in revision checkout-00002-nt5 (ReplaceService at 2026-10-18T22:22:37Z by oncall@example.com) was the env var UPSTREAM_TIMEOUT_MS, which went from "2000" in checkout-00001-ldp to "1". The image digest, code, resources and probe are the same in both revisions. The handler calls the inventory upstream with timeout=T/1000, which is now 0.001 s. That call fails with "URLError: <urlopen error timed out>", and the handler returns 503 "inventory unavailable". Every recent error log on checkout-00002-nt5 says "inventory lookup failed after 1 ms" with timeout_ms=1, followed by a 503 at about 25 ms latency. The cause is a timeout that is far too short, not an inventory outage. The previous revision started with "inventory timeout 2000 ms", and my search turned up no error entries from it.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/cloud_run_service/checkout (revision checkout-00002-nt5, us-central1)

**Evidence**
- `gcp_list_log_entries`: checkout-00002-nt5 stdout ERROR, repeating about every 2.5 s through 22:34:31Z: "inventory lookup failed after 1 ms: URLError: <urlopen error timed out>" timeout_ms=1 upstream=inventory, each followed by a request log entry for GET / with status 503 and about 0.024 s latency
- `gcp_list_log_entries`: Audit log: ReplaceService on services/checkout at 2026-10-18T22:22:37Z by oncall@example.com created revision checkout-00002-nt5 with env UPSTREAM_TIMEOUT_MS="1", same image digest sha256:2b4f19da...; revision became Ready at 22:24:18Z
- `gcp_list_log_entries`: Audit log: earlier revision checkout-00001-ldp (CreateService at 22:17Z) had UPSTREAM_TIMEOUT_MS="2000" and logged "checkout listening, inventory timeout 2000 ms"

**Recommendations**
1. Roll back now by sending 100% of traffic to the previous revision: gcloud run services update-traffic checkout --region us-central1 --to-revisions checkout-00001-ldp=100 --project shop-prod-4f2a (this needs approval)
2. Or deploy a new revision with UPSTREAM_TIMEOUT_MS set back to 2000: gcloud run services update checkout --update-env-vars UPSTREAM_TIMEOUT_MS=2000
3. Check that the 503 rate drops in the run.googleapis.com/request_count metric (response_code_class=5xx) and that the 'inventory lookup failed' errors stop
4. Ask oncall@example.com why the timeout was changed to 1 ms (it may have been meant as seconds or a typo), and add validation or a lower bound for the timeout value plus a canary or traffic-split step for config-only deploys

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND severity>=ERROR", "orderBy": "timestamp desc", "pageSize": 10}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\"", "orderBy": "timestamp desc", "pageSize": 10}
3. `read_more` {"result_id": "ra9c89c", "grep": "protoPayload"}
4. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND protoPayload.methodName:\"Service\"", "orderBy": "timestamp desc", "pageSize": 5}
5. `read_more` {"result_id": "ra9c89c", "grep": "checkout-00001", "fields": ["timestamp", "protoPayload.methodName", "protoPayload.resourceName", "httpRequest.status", "jsonPayload.message", "protoPayload.response.spec.containers"]}
