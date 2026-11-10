## Checkout is failing because of a bad deploy. Revision checkout-00002-nt5, deployed at 22:22 UTC on 2026-10-18 by oncall@example.com, lowered the inventory call timeout (UPSTREAM_TIMEOUT_MS) from 2000 ms to 1 ms. Inventory lookups now time out and the service returns 503.

**Root cause** (high confidence, `bad_rollout`): oncall@example.com ran a ReplaceService on checkout at 2026-10-18T22:22:37Z, which created revision checkout-00002-nt5. Its only setting change is env UPSTREAM_TIMEOUT_MS going from "2000" (revision checkout-00001) to "1"; the image digest and code are the same. The handler passes timeout=T/1000 to urlopen for the inventory lookup and returns 503 'inventory unavailable' on any exception. A 1 ms timeout can't be met, so requests fail with 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' (timeout_ms=1) and 503 after about 24–28 ms. Revision 00001 started with 'inventory timeout 2000 ms'. Inventory itself doesn't appear to be down; the timeout is wrong.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/CloudRunService/checkout

**Evidence**
- `gcp_list_log_entries`: Error logs for checkout revision checkout-00002-nt5 repeat 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' (timeout_ms=1, upstream=inventory), and each matching request returns HTTP 503 in about 0.024–0.028 s (e.g. 22:34:30Z).
- `gcp_list_log_entries`: Audit activity log: oncall@example.com ran google.cloud.run.v1.Services.ReplaceService on services/checkout at 2026-10-18T22:22:37Z. Before that: CreateService at 22:17:04Z and SetIamPolicy at 22:17:08Z.
- `gcp_list_log_entries`: system_event audit log: revision checkout-00002-nt5 (created 22:22:38Z, Ready at 22:24:18Z) has env UPSTREAM_TIMEOUT_MS="1". Revision checkout-00001 has UPSTREAM_TIMEOUT_MS="2000" with the same image digest sha256:2b4f19da... and the same code.
- `gcp_list_log_entries`: Revision checkout-00001 logged 'checkout listening, inventory timeout 2000 ms' at 22:17:15Z. The code returns 503 'inventory unavailable' on any exception during the inventory urlopen(timeout=T/1000).

**Recommendations**
1. Roll traffic back to the last good revision: gcloud run services update-traffic checkout --region us-central1 --to-revisions checkout-00001=100 (needs approval).
2. Or deploy a fix that sets UPSTREAM_TIMEOUT_MS back to 2000: gcloud run services update checkout --region us-central1 --update-env-vars UPSTREAM_TIMEOUT_MS=2000.
3. Check the fix with the checkout 5xx rate (run.googleapis.com/request_count by response_code_class) and confirm the 'inventory lookup failed' errors stop.
4. Ask oncall@example.com why the timeout was set to 1 ms; it may have been meant as seconds or a typo. Add validation or a minimum for UPSTREAM_TIMEOUT_MS in the code or deploy pipeline.
5. Consider gradual traffic splitting or a canary for checkout deploys so a bad revision doesn't take 100% of traffic right away.

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND severity>=ERROR", "orderBy": "timestamp desc", "pageSize": 20}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\"", "orderBy": "timestamp desc", "pageSize": 20}
3. `read_more` {"result_id": "rf00460", "grep": "methodName"}
4. `read_more` {"result_id": "rf00460", "grep": "cloudaudit.googleapis.com%2Factivity", "fields": ["timestamp", "protoPayload.methodName", "protoPayload.resourceName", "protoPayload.authenticationInfo.principalEmail", "protoPayload.request.spec.template.spec.containers"]}
5. `read_more` {"result_id": "rf00460", "grep": "checkout-00001", "fields": ["timestamp", "severity", "logName", "jsonPayload.message", "httpRequest.status", "protoPayload.response.spec.containers"]}
