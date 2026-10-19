## Checkout 5xx spike is caused by the new revision checkout-00002-nt5, which fails every inventory lookup with a 1 ms timeout and returns 503. The previous revision checkout-00001-ldp was serving 2xx traffic and its request rate dropped to zero as 00002 took over, so the rollout is the likely trigger.

**Root cause** (medium confidence, `bad_rollout`): Revision checkout-00002-nt5 has a timeout of about 1 ms for the inventory upstream (log: timeout_ms=1, 'inventory lookup failed after 1 ms: URLError: timed out'). Nearly every request therefore fails with 503. The earlier revision checkout-00001-ldp was healthy, so the new revision's config or code is the likely cause. The rollout audit log query did not return a usable result, so the exact deploy time and author are unconfirmed.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/cloud-run-service/checkout, shop-prod-4f2a/cloud-run-revision/checkout-00002-nt5

**Evidence**
- `gcp_list_log_entries`: Repeated ERROR entries on revision checkout-00002-nt5: 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>', timeout_ms=1, upstream=inventory, followed by GET / returning HTTP 503 about 25 ms later.
- `gcp_query_range`: request_count by response_code_class over the last 2h: revision checkout-00001-ldp 2xx rose to ~72 req/5m then dropped to 0 by the last samples; revision checkout-00002-nt5 5xx went from ~7 to ~117 to 124 req/5m. Traffic has shifted to the failing revision.
- `gcp_list_log_entries`: Audit-log query for recent Cloud Run service create/update events (since 21:00Z) returned unfiltered results, so no rollout event was confirmed. The rollout hypothesis rests on the revision traffic shift alone.

**Recommendations**
1. Human approval needed: shift 100% of checkout traffic back to checkout-00001-ldp (for example with gcloud run services update-traffic checkout --to-revisions=checkout-00001-ldp=100) to stop the 5xx spike now.
2. Compare the env vars and config of checkout-00002-nt5 with checkout-00001-ldp, focusing on the inventory timeout setting (currently 1 ms). Correct it to a realistic value such as a few seconds.
3. Check the inventory service's health and latency independently, since the 1 ms timeout could be a misconfiguration rather than a dependency failure.
4. Confirm the deploy time and author of checkout-00002-nt5 in Cloud Audit Logs, then add a canary or timeout-value validation step before future rollouts.

**Tool calls**
1. `gcp_list_log_entries`
2. `gcp_query_range`
3. `gcp_list_log_entries`
4. `gcp_list_log_entries`
5. `gcp_list_log_entries`
6. `gcp_list_log_entries`
