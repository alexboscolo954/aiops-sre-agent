## The checkout Cloud Run service is returning 5xx on revision checkout-00002-nt5, which is now serving all traffic. Its logs show the inventory lookup failing after a 1 ms timeout, and the older revision checkout-00001-ldp, which returned 2xx, has dropped to zero. The 1 ms timeout points to a bad config in the new revision.

**Root cause** (medium confidence, `bad_rollout`): Revision checkout-00002-nt5 fails every request that calls the inventory upstream. Its logs repeat 'inventory lookup failed after 1 ms: URLError: timed out' with timeout_ms=1, and the resulting GET / requests return HTTP 503 with latency about 24-28 ms. The 5xx rate on checkout-00002-nt5 rose from about 7 to about 124 requests per 5 minutes while checkout-00001-ldp fell from about 72 to 0 2xx requests per 5 minutes, so traffic shifted to the new revision. A 1 ms upstream timeout is almost certainly a misconfiguration, not a real upstream latency, and it is most likely part of the 00002 change. The audit-log query did not return any deployment or config entries, so the exact change is not confirmed.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/CloudRunService/checkout, shop-prod-4f2a/CloudRunRevision/checkout-00002-nt5

**Evidence**
- `gcp_list_log_entries`: Recent ERROR entries for resource checkout / revision checkout-00002-nt5 show 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' (timeout_ms: 1, upstream: inventory), followed by HTTP 503 responses on GET / with latency about 0.024-0.028s.
- `gcp_query_range`: Over the last 3h, the 5xx request rate on checkout-00002-nt5 rose from about 7.2 to 117 to 124 per 5-minute window, while the 2xx rate on checkout-00001-ldp fell from about 72 to 0 in the same window.
- `gcp_list_log_entries`: The cloudaudit activity-log queries for checkout deploys and config changes returned the same stdout/request entries as the error query rather than audit entries, so the rollout change and its time could not be confirmed.

**Recommendations**
1. Shift 100% of checkout traffic back to revision checkout-00001-ldp, which served 2xx before the alert. This needs human approval.
2. Check the configuration of checkout-00002-nt5 for the inventory client timeout (timeout_ms=1) and correct it, for example to a realistic value of a few seconds, then redeploy as a canary.
3. Confirm the inventory service is healthy by checking its own error rate and latency, so the timeout is not hiding a real upstream outage.
4. Pull the Cloud Audit Logs for the checkout service around the time 00002 was deployed to confirm what changed and who changed it. The audit query in this run returned no usable entries.

**Tool calls**
1. `gcp_list_log_entries`
2. `gcp_list_log_entries`
3. `gcp_query_range`
4. `gcp_list_log_entries`
5. `gcp_list_log_entries`
