## Checkout Cloud Run service is returning 5xx on the new revision checkout-00002-nt5, which every request now reaches. Its inventory lookups fail with a 1 ms timeout, and the failures began right after oncall@example.com replaced the service at about 22:22-22:24 UTC on 2026-10-18.

**Root cause** (medium confidence, `bad_rollout`): Revision checkout-00002-nt5, deployed by a ReplaceService call from oncall@example.com at 22:22:37-22:24:18 UTC, makes inventory calls with timeout_ms=1. Each lookup fails with 'URLError: urlopen error timed out' after about 1 ms, and the handler then returns HTTP 503 in about 25 ms. The previous revision checkout-00001-ldp was still serving 2xx until the traffic shift. Prometheus shows its 2xx rate falling to 0 while checkout-00002-nt5 5xx rises to about 124 requests per 5 minutes, so the bad revision now takes all traffic. The 1 ms timeout is the likely config fault, but I did not read the revision spec to confirm it, so the exact cause of the bad value is unverified.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/Service/checkout, shop-prod-4f2a/Revision/checkout-00002-nt5

**Evidence**
- `gcp_list_log_entries`: Errors on revision checkout-00002-nt5 from 22:34:21 to 22:34:31 UTC: stdout 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' with timeout_ms 1, and requests logs with status 503 on GET / for the same revision.
- `gcp_list_log_entries`: Audit log: google.cloud.run.v1.Services.ReplaceService on namespaces/shop-prod-4f2a/services/checkout at 22:22:37.9 UTC by oncall@example.com, followed by ReplaceService on revision checkout-00002-nt5 at 22:22:38.6, 22:24:16.0 and 22:24:18.6 UTC. Earlier create of checkout-00001-ldp at 22:17 was the working revision.
- `gcp_query_range`: request_count by response_code_class and revision: checkout-00001-ldp 2xx drops from about 72 req/5m to 0 by the last two buckets; checkout-00002-nt5 5xx goes from 7.2 to 117 to 124 req/5m over the same window.

**Recommendations**
1. Ask for approval to shift 100% of checkout traffic back to checkout-00001-ldp, which was serving 2xx before the change, to stop the 5xx.
2. Read the checkout-00002-nt5 revision spec (for example with gcloud run revisions describe) and confirm the inventory timeout is set to 1 ms and what the intended value is.
3. Fix the inventory timeout in configuration and redeploy as a new revision, canary it on a small traffic share, and confirm 5xx stays near zero before shifting all traffic.
4. Check the inventory service health, since timeouts can also come from a slow dependency, and confirm the 1 ms value is the only cause before closing the incident.
5. Review the 22:22-22:24 deploy by oncall@example.com for what else changed in that replace, and add a pre-deploy check that rejects timeouts below a sane minimum.

**Tool calls**
1. `gcp_list_log_entries`
2. `gcp_list_log_entries`
3. `gcp_query_range`
4. `gcp_list_log_entries`
5. `gcp_list_log_entries`
6. `read_more`
7. `read_more`
