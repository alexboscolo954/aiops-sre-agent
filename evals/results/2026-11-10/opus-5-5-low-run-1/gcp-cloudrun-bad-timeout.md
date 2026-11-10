## Cloud Run service checkout returns 503s on revision checkout-00002-nt5. Every inventory lookup on that revision times out after 1 ms (timeout_ms=1). oncall@example.com deployed the revision at 22:22:37Z, and the errors in the logs started after that.

**Root cause** (high confidence, `bad_rollout`): oncall@example.com deployed a new revision, checkout-00002-nt5, with Services.ReplaceService at 2026-10-18T22:22:37Z. On that revision the inventory call fails with "inventory lookup failed after 1 ms: URLError: <urlopen error timed out>" and timeout_ms=1. With a 1 ms limit, no inventory call can finish, so requests fail with 503 in about 25 ms. The most likely cause is a misconfigured inventory timeout, probably a value or unit mistake such as 1 instead of 1000, introduced in this revision. I did not look at the revision's env/config diff or at logs from checkout-00001-ldp, so it is not proven that the timeout changed in this revision. I also did not check the 5xx-rate metric, so the alert's 'more than half' figure is not confirmed here.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/CloudRunService/checkout

**Evidence**
- `gcp_list_log_entries`: checkout revision checkout-00002-nt5 stdout ERROR: 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>', timeout_ms=1, upstream=inventory, repeated around 22:34Z
- `gcp_list_log_entries`: Request logs for checkout-00002-nt5 show GET / returning status 503 with latency about 0.024-0.028s
- `gcp_list_log_entries`: Audit log: oncall@example.com called google.cloud.run.v1.Services.ReplaceService on services/checkout at 2026-10-18T22:22:37Z, creating revision checkout-00002-nt5. The prior revision checkout-00001-ldp was created at 22:17Z.

**Recommendations**
1. Roll traffic back to the previous revision: gcloud run services update-traffic checkout --to-revisions=checkout-00001-ldp=100 --region us-central1 --project shop-prod-4f2a
2. Compare the env vars/config of checkout-00002-nt5 and checkout-00001-ldp to find the inventory timeout setting that is now 1 ms, and confirm with oncall@example.com what the 22:22Z change was meant to do.
3. Fix the timeout value (likely seconds vs ms, e.g. 1000 ms), redeploy, and check that the 5xx rate drops below the alert threshold.
4. Add validation or a minimum for the timeout config so values this low are rejected before deploy.

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND severity>=ERROR", "orderBy": "timestamp desc", "pageSize": 10}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\"", "orderBy": "timestamp desc", "pageSize": 10}
3. `read_more` {"result_id": "r4b6294", "grep": "methodName", "fields": ["timestamp", "protoPayload.methodName", "protoPayload.resourceName", "protoPayload.authenticationInfo.principalEmail"]}
