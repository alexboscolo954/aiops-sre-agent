## Since 22:24 UTC, checkout returns 503 on almost every request. Revision checkout-00002-nt5, deployed by oncall@example.com at 22:22, sets UPSTREAM_TIMEOUT_MS=1, so every inventory lookup times out after 1 ms. The code's default is 2000 ms.

**Root cause** (high confidence, `bad_rollout`): At 22:22:37 UTC, oncall@example.com ran ReplaceService on checkout, which created revision checkout-00002-nt5 (Ready at 22:24:18, 100% of traffic on latestRevision). That revision sets env UPSTREAM_TIMEOUT_MS=1. The code reads it as `T = int(os.environ.get("UPSTREAM_TIMEOUT_MS", "2000"))` and passes timeout=T/1000 (0.001 s) to urlopen for the inventory call. Every request logs 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' (timeout_ms=1) and returns 503 in about 25 ms. The inventory service is not slow; checkout's own 1 ms timeout is too short for any real network call. I haven't confirmed that the previous revision checkout-00001-ldp served without errors, or what timeout it used.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/cloud_run_service/checkout

**Evidence**
- `gcp_list_log_entries`: checkout-00002-nt5 stdout, repeating every few seconds up to 22:34:31Z: 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>', timeout_ms=1, upstream=inventory. Each one is paired with a request log of GET / status 503, latency ~0.024s.
- `gcp_list_log_entries`: Activity audit log: oncall@example.com ran google.cloud.run.v1.Services.ReplaceService on services/checkout at 2026-10-18T22:22:37Z (traffic latestRevision 100%). Revision checkout-00002-nt5 replaced checkout-00001-ldp, which was created at 22:17.
- `gcp_list_log_entries`: system_event audit for revision checkout-00002-nt5: container env UPSTREAM_TIMEOUT_MS="1". Code default is "2000" and the code calls urlopen(..., timeout=T/1000). Revision became Ready at 22:24:18Z.

**Recommendations**
1. Roll back first: send 100% of traffic to the previous revision checkout-00001-ldp (gcloud run services update-traffic checkout --region us-central1 --to-revisions checkout-00001-ldp=100). It needs human approval.
2. Or deploy a fix: remove UPSTREAM_TIMEOUT_MS or set it to a sane value (e.g. 2000) with gcloud run services update checkout --region us-central1 --update-env-vars UPSTREAM_TIMEOUT_MS=2000.
3. Check that the 5xx rate drops and the 'inventory lookup failed' errors stop in the checkout request and stdout logs.
4. Ask oncall@example.com why the timeout was set to 1. It may have been meant as seconds instead of ms. Add validation or a minimum for timeout env values in the deploy pipeline or the code.
5. Think about raising maxScale above 1 (autoscaling.knative.dev/maxScale=1) and adding a readiness check for the upstream. This is not the cause, but it limits resilience.

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND severity>=ERROR", "orderBy": "timestamp desc", "pageSize": 10}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\"", "orderBy": "timestamp desc", "pageSize": 10}
3. `read_more` {"result_id": "r43b801", "grep": "cloudaudit", "fields": ["timestamp", "protoPayload.methodName", "protoPayload.resourceName", "protoPayload.authenticationInfo.principalEmail", "protoPayload.request"]}
4. `read_more` {"result_id": "r43b801", "grep": "TIMEOUT"}
