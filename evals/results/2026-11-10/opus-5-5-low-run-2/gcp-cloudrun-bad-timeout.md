## Since revision checkout-00002-nt5 went live at about 22:24 UTC on 2026-10-18, checkout has been returning 503s. That revision sets UPSTREAM_TIMEOUT_MS=1, so each call to inventory times out after 1 ms. The code's default is 2000 ms. Rolling back to the previous revision should fix it.

**Root cause** (high confidence, `bad_rollout`): oncall@example.com deployed Cloud Run revision checkout-00002-nt5 with gcloud. It became Ready at 22:24:18 UTC. It sets the env var UPSTREAM_TIMEOUT_MS to "1", where the code's default is 2000 ms. The inventory call (urlopen) therefore gives up after 0.001 s. Every request logs 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' and gets a 503 in about 25 ms. I didn't open the previous revision's config, so I'm inferring that it worked from the 2000 ms default.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/CloudRunService/checkout

**Evidence**
- `gcp_list_log_entries`: checkout-00002-nt5 stdout keeps logging ERROR 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' (timeout_ms=1). Matching request logs show status 503 with latency of about 0.024 s, around 22:34 UTC.
- `gcp_list_log_entries`: Audit log: /Services.ReplaceService by oncall@example.com (gcloud 589.0.0) created revision checkout-00002-nt5, Ready at 2026-10-18T22:24:18Z, with env UPSTREAM_TIMEOUT_MS="1". The code reads it as T = int(os.environ.get("UPSTREAM_TIMEOUT_MS", "2000")).

**Recommendations**
1. Send 100% of traffic back to the previous checkout revision (e.g. gcloud run services update-traffic checkout --to-revisions=<previous-revision>=100 --region us-central1). Confirm first that it doesn't set UPSTREAM_TIMEOUT_MS=1.
2. Or set UPSTREAM_TIMEOUT_MS to a sensible value (e.g. 2000) or remove it, then redeploy.
3. Watch the 5xx rate drop with run_googleapis_com:request_count{monitored_resource="cloud_run_revision",service_name="checkout"}.
4. Ask oncall@example.com why the value was set to 1, and add validation to the deploy so timeouts this low are rejected.
5. Look into autoscaling.knative.dev/maxScale=1 on the revision template, which allows only one instance.

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND severity>=ERROR", "orderBy": "timestamp desc", "pageSize": 10}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\"", "orderBy": "timestamp desc", "pageSize": 10}
3. `read_more` {"result_id": "r5f3206", "grep": "methodName"}
