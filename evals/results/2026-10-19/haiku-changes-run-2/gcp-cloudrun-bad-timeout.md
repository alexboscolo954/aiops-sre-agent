## Checkout Cloud Run service is returning almost only 503s since revision checkout-00002-nt5 took over from checkout-00001-ldp around 22:24Z. Its logs show every inventory lookup failing with a 1 ms timeout (timeout_ms: 1), which points to a bad config rollout rather than an inventory outage. Rolling traffic back to checkout-00001-ldp is the fastest mitigation, pending approval.

**Root cause** (medium confidence, `bad_rollout`): Revision checkout-00002-nt5 (new rollout) makes the inventory upstream call with a 1 ms timeout, so nearly every request fails with URLError timed out and returns 503. The previous revision checkout-00001-ldp served 200s until about 22:24Z, then traffic shifted to 00002. The exact deploy event was not confirmed because the log queries kept returning the same truncated output.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/cloudrun/checkout

**Evidence**
- `gcp_list_log_entries (severity>=ERROR, cloud_run_revision service checkout)`: Repeated ERROR stdout 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' with timeout_ms: 1, upstream: inventory, all on revision checkout-00002-nt5; matching GET requests return status 503 with latencies around 25 ms.
- `gcp_list_timeseries (run.googleapis.com/request_count, grouped by response_code_class and revision)`: checkout-00001-ldp: 2xx 37 then 83 per 5 min until about 22:24Z, then 0. checkout-00002-nt5: 5xx 113 (22:24-22:29Z) and 100 (22:29-22:34Z), with no 2xx. Traffic moved from 00001 to 00002 and all of it now fails.
- `gcp_list_log_entries (run.googleapis.com audit/serviceName, inventory WARNING+)`: Queries for recent Cloud Run deploy events and inventory-service warnings returned only the same checkout 00002 error entries, so no deploy record or inventory-side failure was found.

**Recommendations**
1. Get approval, then shift 100% of checkout traffic back to checkout-00001-ldp (gcloud run services update-traffic checkout --to-revisions=checkout-00001-ldp=100). This is the fastest way to stop the 5xx spike.
2. Diff checkout-00002-nt5 against checkout-00001-ldp, especially the inventory client timeout (timeout_ms: 1). Confirm the change in the deploy record before redeploying a fix.
3. Check the inventory service's health and latency directly (its Cloud Run revisions and request logs). Rule out an upstream problem before blaming the config.
4. Once a corrected revision is deployed, canary it at a small traffic share and watch 5xx rate and inventory timeout logs before moving all traffic.
5. Add a guard against sub-second upstream timeouts in config review or CI, and alert on checkout 5xx by revision so a bad rollout is caught early.

**Tool calls**
1. `gcp_list_log_entries`
2. `gcp_list_timeseries`
3. `gcp_list_log_entries`
4. `gcp_list_log_entries`
5. `gcp_list_log_entries`
