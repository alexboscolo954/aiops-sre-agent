## Revision checkout-00002-nt5 broke Cloud Run service checkout. oncall@example.com deployed it at 22:22:37Z on 2026-10-18 and it changed UPSTREAM_TIMEOUT_MS from 2000 to 1. Every inventory lookup now times out after 1 ms, and requests get a 503 "inventory unavailable" response.

**Root cause** (high confidence, `bad_rollout`): At 2026-10-18T22:22:37Z, oncall@example.com called ReplaceService (gcloud) on service checkout. This created revision checkout-00002-nt5 with env UPSTREAM_TIMEOUT_MS="1". The previous revision, checkout-00001-ldp, created at 22:17, had "2000". The code was unchanged: both revisions run the same script on the same image digest (sha256:2b4f19da…). The env var is the only difference I found. The handler passes T/1000 seconds as the urlopen timeout for the inventory call, so a 1 ms limit is too short to finish a lookup. Each request logs "inventory lookup failed after 1 ms: URLError: <urlopen error timed out>" (timeout_ms=1) and returns 503 in about 24–28 ms. The new revision went Ready at 22:24:18Z, and every recent ERROR entry comes from checkout-00002-nt5. One gap: I did not pull request metrics, so I have not measured how healthy revision 00001 was or the exact share of 5xx responses.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/cloud_run_service/checkout

**Evidence**
- `gcp_list_log_entries`: Recent ERROR logs for service checkout, all on revision checkout-00002-nt5: stdout 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' (timeout_ms=1, upstream=inventory), each followed by a GET / request log with status 503 and latency ~0.024–0.028s.
- `gcp_list_log_entries`: Audit log: at 2026-10-18T22:22:37.93Z, principal oncall@example.com called google.cloud.run.v1.Services.ReplaceService on namespaces/shop-prod-4f2a/services/checkout. This created revision checkout-00002-nt5 with env UPSTREAM_TIMEOUT_MS="1", which went Ready at 22:24:18Z.
- `gcp_list_log_entries`: Audit log CreateService at 22:17:15Z: revision checkout-00001-ldp had the same code and image digest but env UPSTREAM_TIMEOUT_MS="2000". The only change I found between the revisions is the timeout value.
- `gcp_list_log_entries`: In the container source (both revisions): urlopen(..., timeout=T / 1000), and any exception returns 503 b"inventory unavailable". So T=1 gives a 1 ms timeout.

**Recommendations**
1. Roll back by sending 100% of traffic to the last good revision: gcloud run services update-traffic checkout --region us-central1 --to-revisions checkout-00001-ldp=100. This needs human approval.
2. Alternatively, deploy a new revision with UPSTREAM_TIMEOUT_MS=2000 (or the intended value in ms): gcloud run services update checkout --region us-central1 --update-env-vars UPSTREAM_TIMEOUT_MS=2000.
3. Check that the 503 rate falls and that 'inventory lookup failed' errors stop, using run.googleapis.com/request_count by response_code_class and revision_name.
4. Ask oncall@example.com what the change meant to do. The value may have been entered in seconds instead of milliseconds.
5. Add validation or a minimum for UPSTREAM_TIMEOUT_MS. Also consider a canary or gradual traffic split for config-only deploys, so a bad value can't take all traffic at once.

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND severity>=ERROR", "orderBy": "timestamp desc", "pageSize": 10}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\"", "orderBy": "timestamp desc", "pageSize": 10}
3. `read_more` {"result_id": "rf2c20d", "grep": "methodName"}
4. `read_more` {"result_id": "rf2c20d", "grep": "checkout-00001", "fields": ["timestamp", "protoPayload.methodName", "protoPayload.resourceName", "protoPayload.authenticationInfo", "protoPayload.response.spec.containers", "protoPayload.response.spec.template.spec.containers"]}
