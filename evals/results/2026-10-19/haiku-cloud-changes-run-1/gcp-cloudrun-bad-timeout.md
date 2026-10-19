## The checkout Cloud Run service is returning mostly 503s because its newest revision, checkout-00002-nt5, fails every inventory lookup with a 1 ms timeout (timeout_ms: 1). The previous revision, checkout-00001-ldp, was serving 2xx traffic earlier but has had zero requests in the last 10 minutes, so traffic appears to have moved to the bad revision. Rolling traffic back to checkout-00001-ldp is the fastest mitigation.

**Root cause** (medium confidence, `bad_rollout`): A new revision (checkout-00002-nt5) was deployed with an inventory-service timeout of 1 ms, far too short for a real call. Every inventory lookup times out, and the handler returns 503. The 1 ms value is the most likely misconfiguration, but I did not see the revision's config diff, so this is inferred from the logs.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/Service/checkout, shop-prod-4f2a/Revision/checkout-00002-nt5

**Evidence**
- `gcp_list_log_entries (run.googleapis.com/stdout, severity>=ERROR)`: Repeated ERROR 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' with jsonPayload timeout_ms: 1, upstream: inventory, all from revision checkout-00002-nt5.
- `gcp_list_log_entries (run.googleapis.com/requests, severity>=ERROR)`: GET / requests to checkout on revision checkout-00002-nt5 returning status 503 with latency of about 0.024-0.028s, matching the inventory timeouts.
- `gcp_list_timeseries (run.googleapis.com/request_count, grouped by revision and response_code_class)`: checkout-00002-nt5: 503 (5xx) counts of 113 and 100 in the last two 5-minute windows, with no 2xx. checkout-00001-ldp: 2xx counts of 37 and 83 in earlier windows, then 0 in the last two windows.
- `gcp_list_log_entries (cloudaudit activity, checkout, since 21:00Z)`: The audit query returned the same entries as the error-log query and showed no deploy record, so I could not confirm when or by whom checkout-00002-nt5 was deployed.

**Recommendations**
1. Shift checkout traffic back to checkout-00001-ldp, which was healthy, using a traffic split or rollback. This needs human approval and I have not run it.
2. Confirm the revision diff: compare the environment/config of checkout-00002-nt5 with checkout-00001-ldp and find where the inventory timeout is set to 1 ms.
3. Fix the inventory client timeout to a sane value (for example a few hundred ms to a few seconds), then redeploy as a new revision and roll out gradually.
4. Check the audit log for who deployed checkout-00002-nt5 and when, to confirm the change and its timing. The audit query I ran did not return it.
5. After rollback, confirm that the 5xx rate drops and that 2xx traffic returns to checkout-00001-ldp. Also check the inventory service's own health, since a 1 ms timeout could mask a real inventory slowdown.

**Tool calls**
1. `gcp_list_log_entries`
2. `gcp_list_log_entries`
3. `gcp_list_timeseries`
4. `gcp_list_log_entries`
