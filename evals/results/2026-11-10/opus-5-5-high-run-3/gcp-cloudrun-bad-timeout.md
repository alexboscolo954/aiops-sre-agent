## Nearly every request to the Cloud Run service checkout is failing with 503. Revision checkout-00002-nt5, deployed at 22:22:37Z on 2026-10-18 by oncall@example.com, changed UPSTREAM_TIMEOUT_MS from 2000 to 1. The inventory call now always times out after 1 ms.

**Root cause** (high confidence, `bad_rollout`): The deploy at 2026-10-18T22:22:37Z (google.cloud.run.v1.Services.ReplaceService by oncall@example.com) created revision checkout-00002-nt5 with the env var UPSTREAM_TIMEOUT_MS="1". The previous revision, checkout-00001-ldp, had "2000". Both revisions run the same inline code, which uses this value as the urllib timeout (T/1000 seconds) for the inventory lookup and returns 503 "inventory unavailable" on any exception. A 1 ms timeout can't finish a network round trip, so every request fails. The logs show "inventory lookup failed after 1 ms: URLError: <urlopen error timed out>" (timeout_ms=1), each followed by a 503 in about 24–28 ms, all on checkout-00002-nt5. The new revision became Ready at 22:24:18Z, and the 503s run until at least 22:34:31Z. Nothing points to inventory itself being down: the failures come from the timeout setting, not from the upstream.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/cloud_run_service/checkout

**Evidence**
- `gcp_list_log_entries`: Checkout revision checkout-00002-nt5 logs repeated ERRORs 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' (timeout_ms=1, upstream=inventory), each paired with an HTTP 503 request log of about 24–28 ms latency, through 2026-10-18T22:34:31Z.
- `gcp_list_log_entries`: Activity audit log: google.cloud.run.v1.Services.ReplaceService on namespaces/shop-prod-4f2a/services/checkout by oncall@example.com at 2026-10-18T22:22:37Z. The request replaced the service spec, which until then was serving checkout-00001-ldp.
- `gcp_list_log_entries`: System-event audit log: revision checkout-00002-nt5 spec has env UPSTREAM_TIMEOUT_MS="1" and became Ready at 22:24:18Z ('Deploying revision succeeded in 1m40.46s'). It is created by the same operation-id as the 22:22:37 ReplaceService call.
- `gcp_list_log_entries`: System-event audit log for CreateService at 22:17 shows the first revision, checkout-00001-ldp, with the same code but env UPSTREAM_TIMEOUT_MS="2000". Only the timeout changed between revisions.

**Recommendations**
1. Roll back by sending 100% of traffic to the previous revision: gcloud run services update-traffic checkout --region us-central1 --to-revisions checkout-00001-ldp=100. Or redeploy with UPSTREAM_TIMEOUT_MS=2000. This needs human approval.
2. Check that the 5xx rate drops: request logs should return 200 and the 'inventory lookup failed' errors should stop.
3. Ask oncall@example.com why the timeout was set to 1. If it was meant as 1 second, the value is in milliseconds and should be 1000 or more.
4. Add validation or a minimum for UPSTREAM_TIMEOUT_MS, and send checkout deploys through a canary or gradual traffic split so a bad revision doesn't take all traffic at once.

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND severity>=ERROR", "orderBy": "timestamp desc", "pageSize": 20}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\"", "orderBy": "timestamp desc", "pageSize": 20}
3. `read_more` {"result_id": "r1aed40", "grep": "methodName"}
4. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\" AND resource.labels.service_name=\"checkout\"", "orderBy": "timestamp desc", "pageSize": 5}
5. `read_more` {"result_id": "rae218b", "grep": "checkout-00001"}
6. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND resource.labels.revision_name=\"checkout-00001-ldp\" AND logName=\"projects/shop-prod-4f2a/logs/run.googleapis.com%2Frequests\"", "orderBy": "timestamp des
7. `read_more` {"result_id": "r859e1a", "grep": "\"status\": 200", "fields": ["timestamp", "resource.labels.revision_name", "httpRequest.status"]}
