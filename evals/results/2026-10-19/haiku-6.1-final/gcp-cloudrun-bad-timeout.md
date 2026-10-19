## Cloud Run service checkout is returning 5xx on its new revision checkout-00002-nt5, which began taking traffic around 22:24Z while checkout-00001-ldp served 2xx. Logs show every inventory lookup on the new revision failing with a 1 ms timeout, so the 5xx rate is likely caused by the new revision's configuration. I could not confirm the deploy from the audit log.

**Root cause** (medium confidence, `bad_rollout`): The new revision checkout-00002-nt5 has an inventory upstream timeout of about 1 ms (timeout_ms: 1). Every inventory call times out and the handler returns HTTP 503. The previous revision checkout-00001-ldp did not show this and was serving 2xx. This points to a bad config value in the 00002 rollout, most likely the timeout setting.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/CloudRunService/checkout, shop-prod-4f2a/CloudRunRevision/checkout-00002-nt5

**Evidence**
- `gcp_list_log_entries`: Errors on checkout-00002-nt5 repeat as 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' with timeout_ms: 1 and upstream: inventory. The matching run.googleapis.com/requests entries are GET / with status 503 and latency about 0.024s.
- `gcp_query_range`: Request rate by revision over the last 3h: checkout-00001-ldp shows 2xx at about 48-72 req per 5m, then 0 from about 22:30Z. checkout-00002-nt5 shows 5xx rising from about 7 to 117 to 124 per 5m, starting around 22:24Z.
- `gcp_list_log_entries`: Audit-log queries for Cloud Run deploy or config changes returned no audit entries, only the same stdout and request logs. The exact deploy time and actor are unverified.

**Recommendations**
1. Ask a human to approve shifting 100% of checkout traffic back to checkout-00001-ldp to stop the 5xx. This is a traffic change and needs approval before it runs.
2. Check the inventory timeout setting in checkout-00002-nt5 against checkout-00001-ldp. A 1 ms value is almost certainly wrong. Correct it in a new revision and roll out after testing.
3. Confirm the inventory service is healthy: check its own errors and latency for the same window, so it is ruled out as a contributor.
4. Pull the Cloud Run revision/configuration change history directly (the Cloud Run console or gcloud run revisions describe) to confirm when 00002 was deployed and by whom, since the audit-log query returned nothing useful.
5. Keep the alert open until checkout 5xx rate drops below the threshold after the rollback or fix.

**Tool calls**
1. `gcp_list_log_entries`
2. `gcp_list_log_entries`
3. `gcp_query_range`
4. `gcp_list_log_entries`
5. `gcp_list_log_entries`
