## Checkout's new revision checkout-00002-nt5 is returning 503s because every inventory lookup times out after 1 ms. Traffic has shifted to it from the previous revision checkout-00001-ldp, which had been serving 2xx, so the 5xx ratio on the service is high. Rolling traffic back to checkout-00001-ldp is the fastest mitigation.

**Root cause** (medium confidence, `bad_rollout`): Revision checkout-00002-nt5 logs 'checkout listening, inventory timeout 1 ms' (timeout_ms=1), and the same revision logs 'checkout listening, inventory timeout 2000 ms' in an earlier entry. Every request then fails with 'inventory lookup failed after 1 ms: URLError: timed out' and returns HTTP 503 (latency about 24-28 ms). Cloud Run request_count shows checkout-00002-nt5 5xx rising from 7.2 to 117 to 124 req/5min, while checkout-00001-ldp 2xx fell from about 72 to 0 over the same window, so traffic moved to the bad revision. The 1 ms timeout value is the likely cause, but I could not pull the deploy audit entry that changed it, so the exact change time and author are unconfirmed.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/Service/checkout, shop-prod-4f2a/Revision/checkout-00002-nt5

**Evidence**
- `gcp_list_log_entries`: Error logs from checkout-00002-nt5 (run.googleapis.com/stdout): 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' with upstream=inventory and timeout_ms=1, paired with httpRequest status 503 on GET / at about 24-28 ms latency.
- `gcp_list_log_entries`: Startup log entries from checkout-00002-nt5 show 'checkout listening, inventory timeout 1 ms' (timeout_ms 1) and an earlier 'checkout listening, inventory timeout 2000 ms' (timeout_ms 2000), indicating the inventory timeout was lowered from 2000 ms to 1 ms in this revision.
- `gcp_query_range`: sum by (response_code_class, revision_name) of run_googleapis_com:request_count for checkout over the last 3h: checkout-00002-nt5 5xx rose 7.2 -> 117 -> 124 req/5m; checkout-00001-ldp 2xx fell 47.8 -> 72.2 -> 0 -> 0, showing traffic moved to the failing revision.
- `gcp_list_log_entries`: Audit-log queries for checkout deploy or config changes (cloudaudit activity) returned only the same run.googleapis.com stdout/request entries, not the revision deploy record, so the change author and time are unverified.

**Recommendations**
1. Propose rolling checkout traffic back to checkout-00001-ldp (100%), which was healthy, pending human approval; do not retry if rejected.
2. Confirm the inventory timeout config on checkout-00002-nt5 against the 2000 ms value in the earlier startup log, then set it back to 2000 ms (or the intended value) in a new revision.
3. Pull the Cloud Run revision deploy record for checkout-00002-nt5 from cloudaudit activity to identify who changed the timeout and when.
4. Check inventory service health, since timeouts to inventory are the failing dependency and a 1 ms budget would fail even a healthy inventory service.
5. After the fix, verify the 5xx ratio on checkout-00002-nt5 drops and the alert clears.

**Tool calls**
1. `gcp_list_log_entries`
2. `gcp_list_log_entries`
3. `gcp_query_range`
4. `gcp_list_log_entries`
5. `gcp_list_log_entries`
6. `read_more`
7. `read_more`
8. `gcp_list_log_entries`
9. `gcp_list_log_entries`
10. `read_more`
11. `read_more`
12. `gcp_list_log_entries`
13. `gcp_query_range`
