## The checkout Cloud Run service is returning 503s from revision checkout-00002-nt5, which is now taking all traffic. Every error log shows the inventory lookup timing out after 1 ms (timeout_ms: 1). The previous revision, checkout-00001-ldp, served 200s without 5xx until about 22:24 UTC and has received no requests since.

**Root cause** (high confidence, `bad_rollout`): Revision checkout-00002-nt5 has an inventory upstream timeout of about 1 ms, most likely a misconfiguration (for example a unit or value error in the timeout setting). Every inventory call fails immediately, so the handler returns 503. The earlier revision 00001 worked, so the new revision is the cause. I did not read the revision's environment configuration, so the exact setting is inferred from the log field timeout_ms: 1.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/cloud_run_revision/checkout (revision checkout-00002-nt5, us-central1)

**Evidence**
- `gcp_list_log_entries`: Repeated ERROR entries from revision checkout-00002-nt5: 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' with timeout_ms: 1, upstream: inventory, followed by GET / responses with status 503 and latency about 0.024 s.
- `gcp_list_timeseries (run.googleapis.com/request_count)`: Over the last 2 hours, revision checkout-00001-ldp had 200 responses (2xx) from 22:14 to 22:24 and zero requests after 22:24. Revision checkout-00002-nt5 had 503 responses (5xx) at 113 in 22:24-22:29 and 100 in 22:29-22:34, with no 2xx.

**Recommendations**
1. Propose rolling back traffic to checkout-00001-ldp (100% traffic). This needs human approval before it is run.
2. Confirm the inventory timeout value in the checkout-00002-nt5 revision configuration (env or config). Expect a value of 1 ms to be a unit or typo error, and correct it in a new revision.
3. After rollback, confirm the 5xx rate falls and inventory lookups succeed. Check that the inventory service itself is healthy, since this investigation did not verify it.
4. Review the deployment that created checkout-00002-nt5 and add a pre-traffic check or canary for inventory-dependent requests.

**Tool calls**
1. `gcp_list_log_entries`
2. `gcp_list_timeseries`
