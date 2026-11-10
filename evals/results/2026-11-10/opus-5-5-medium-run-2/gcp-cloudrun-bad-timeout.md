## Cloud Run service checkout returns 503 on its requests because revision checkout-00002-nt5, deployed at 22:22:37Z on 2026-10-18 by oncall@example.com, set UPSTREAM_TIMEOUT_MS=1. That gives the inventory lookup 1 ms, so it times out and the request fails. Rolling traffic back to checkout-00001-ldp, which used 2000 ms, should fix it.

**Root cause** (high confidence, `bad_rollout`): A new revision changed one setting. In checkout-00002-nt5 (ReplaceService at 2026-10-18T22:22:37Z, creator oncall@example.com), the env var UPSTREAM_TIMEOUT_MS is "1". The code reads it as the urlopen timeout in ms, which is 0.001 s. The previous revision, checkout-00001-ldp, started with "checkout listening, inventory timeout 2000 ms". Under the new revision every logged failure reads "inventory lookup failed after 1 ms: URLError: <urlopen error timed out>" (timeout_ms=1), and the handler returns 503 "inventory unavailable" in about 24-28 ms. Inventory itself is not shown to be down: no call can finish in 1 ms. Strictly this is a config error, but it shipped in a new revision that replaced a working setting, so it counts as a bad rollout. One caveat: I only saw the startup log for 00001, not its request success rate.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/CloudRunService/checkout

**Evidence**
- `gcp_list_log_entries`: checkout-00002-nt5 logs, around 22:34Z, repeat: stdout ERROR "inventory lookup failed after 1 ms: URLError: <urlopen error timed out>" (timeout_ms=1, upstream=inventory), each paired with a request log of GET / status 503 at about 0.024-0.028 s latency.
- `gcp_list_log_entries`: Audit system_event: /Services.ReplaceService created revision checkout-00002-nt5 at 2026-10-18T22:22:38Z (creator oncall@example.com, gcloud 589.0.0) with env UPSTREAM_TIMEOUT_MS="1". The code uses urlopen(timeout=T/1000) and returns 503 on any exception. The revision became Ready at 22:24:18Z.
- `gcp_list_log_entries`: The previous revision checkout-00001-ldp, created at 22:17:06Z with /Services.CreateService, logged at startup "checkout listening, inventory timeout 2000 ms" (22:17:15Z). The ReplaceService that changed the setting is at 22:22:37.93Z.

**Recommendations**
1. Move 100% of traffic back to the last good revision: gcloud run services update-traffic checkout --region us-central1 --to-revisions checkout-00001-ldp=100. This needs human approval.
2. Or deploy a fix: gcloud run services update checkout --region us-central1 --update-env-vars UPSTREAM_TIMEOUT_MS=2000. You can also remove the variable, since 2000 is the code default.
3. Check that the 5xx rate drops, using run_googleapis_com:request_count{monitored_resource="cloud_run_revision",service_name="checkout"} split by response_code_class, and that the "inventory lookup failed" errors stop.
4. Ask oncall@example.com why the timeout was set to 1 (maybe they meant seconds, not ms). Add validation or a minimum for UPSTREAM_TIMEOUT_MS, and a check after deploy that sends a real request, since the TCP startup probe passed while every request failed.
5. Also note that revision 00002 sets autoscaling maxScale=1, against service-level maxScale 20. Confirm whether that was intended.

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND severity>=ERROR", "orderBy": "timestamp desc", "pageSize": 10}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\"", "orderBy": "timestamp desc", "pageSize": 10}
3. `read_more` {"result_id": "r335247", "grep": "cloudaudit"}
4. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.revision_name=\"checkout-00001\" OR (resource.labels.service_name=\"checkout\" AND jsonPayload.message:\"listening\")", "orderBy": "timestamp desc", "pageSize": 5}
5. `read_more` {"result_id": "r254cbb", "grep": "checkout-00001", "fields": ["timestamp", "severity", "jsonPayload.message", "httpRequest.status", "protoPayload.methodName", "resource.labels.revision_name"]}
