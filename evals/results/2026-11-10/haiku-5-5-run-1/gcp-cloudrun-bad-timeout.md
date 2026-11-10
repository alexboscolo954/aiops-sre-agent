## Cloud Run service checkout is returning 5xx on more than half its requests. The new revision checkout-00002-nt5, deployed at 22:24 UTC, is the only one serving 5xx, and its UPSTREAM_TIMEOUT_MS was changed from 2000 to 1 ms. Every inventory check now times out after 1 ms and returns 503. Rolling back to checkout-00001-ldp should stop the errors.

**Root cause** (high confidence, `bad_rollout`): Revision checkout-00002-nt5, deployed by oncall@example.com at 22:24:18 UTC (audit log: Services.ReplaceService), sets UPSTREAM_TIMEOUT_MS=1. The previous revision checkout-00001-ldp ran with 2000 ms (startup log at 22:17:15: "inventory timeout 2000 ms"). The 1 ms inventory check cannot complete, so every request fails with "inventory lookup failed after 1 ms: URLError: timed out" and returns 503. The 5xx rate on checkout-00002-nt5 rose to about 124/s, and 2xx on checkout-00001-ldp fell to 0.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/Service/checkout, shop-prod-4f2a/Revision/checkout-00002-nt5

**Evidence**
- `gcp_query_range`: request_count by revision: checkout-00002-nt5 5xx rose from 7.2/s to 117/s to 124/s; checkout-00001-ldp 2xx fell from 72/s to 0 over the last 15 minutes.
- `gcp_list_log_entries`: Repeated ERROR logs from checkout-00002-nt5: 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>', timeout_ms=1, upstream=inventory; matching requests logged as status 503.
- `gcp_list_log_entries`: Audit log (cloudaudit system_event): Services.ReplaceService on checkout, and a new Revision checkout-00002-nt5 at 2026-10-18T22:24:18Z, by oncall@example.com. The container env UPSTREAM_TIMEOUT_MS value is "1".
- `gcp_list_log_entries`: Startup log of checkout-00001-ldp: 'checkout listening, inventory timeout 2000 ms' (timeout_ms=2000) at 22:17:15Z, so the earlier revision used a 2000 ms timeout.

**Recommendations**
1. Roll traffic back to checkout-00001-ldp (for example, `gcloud run services update-traffic checkout --to-revisions=checkout-00001-ldp=100 --region=us-central1 --project=shop-prod-4f2a`). This needs human approval before it runs.
2. Afterwards, redeploy with UPSTREAM_TIMEOUT_MS set to a realistic value (the previous 2000 ms, or higher if the inventory dependency needs it) and confirm the value in the revision spec before shifting traffic.
3. Check the rollback with the request_count 5xx ratio and the 'inventory lookup failed' log count, which should return to zero.
4. Review the deploy process so that a timeout change of this size needs a canary or review.

**Tool calls**
1. `gcp_query_range` {"name": "projects/shop-prod-4f2a", "location": "global", "query": "sum by (revision_name, response_code_class) (rate(run_googleapis_com:request_count{monitored_resource=\"cloud_run_revision\", service_name=\"checkout\"}[5m]))", "start": "now-3h", "end": "now", "step": "60s"}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND severity>=ERROR", "orderBy": "timestamp desc", "pageSize": 20}
3. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND resource.labels.service_name=\"checkout\"", "orderBy": "timestamp desc", "pageSize": 10}
4. `read_more` {"result_id": "rdf79a1", "grep": "cloudaudit|methodName|setIamPolicy|ReplaceService|UpdateService|CreateRevision", "fields": ["protoPayload.methodName", "protoPayload.resourceName", "protoPayload.authenticationInfo.principalEmail", "timestamp"]}
5. `read_more` {"result_id": "r93a7f7", "grep": "cloudaudit|methodName|ReplaceService|UpdateService|CreateRevision", "fields": ["protoPayload.methodName", "protoPayload.resourceName", "protoPayload.authenticationInfo.principalEmail", "timestamp"]}
6. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND timestamp>=\"2026-10-18T20:00:00Z\"", "orderBy": "timestamp desc", "pageSize": 10}
7. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND resource.labels.revision_name=\"checkout-00002-nt5\" AND jsonPayload.upstream=\"inventory\"", "orderBy": "timestamp asc", "pageSize": 3}
8. `read_more` {"result_id": "r272c03", "grep": "methodName"}
9. `read_more` {"result_id": "r6d1e37", "grep": "timeout_ms", "fields": ["timestamp", "jsonPayload.timeout_ms", "jsonPayload.message"]}
10. `TriageReport` {"summary": "Cloud Run service checkout is returning 5xx on more than half its requests. The new revision checkout-00002-nt5, deployed at 22:24 UTC, is the only one serving 5xx, and its UPSTREAM_TIMEOUT_MS was changed from 2000 to 1 ms. Every inventory check now times out after 1 ms and returns 503.
11. `TriageReport` {"summary": "Cloud Run service checkout is returning 5xx on more than half its requests. The new revision checkout-00002-nt5, deployed at 22:24 UTC, is the only one serving 5xx, and its UPSTREAM_TIMEOUT_MS was changed from 2000 to 1 ms. Every inventory check now times out after 1 ms and returns 503.
