## Cloud Run service checkout returns 503s because revision checkout-00002-nt5, deployed by oncall@example.com at 22:22 UTC on 2026-10-18, calls the inventory upstream with a 1 ms timeout. Every inventory lookup times out right away.

**Root cause** (high confidence, `bad_rollout`): oncall@example.com deployed a new checkout revision (ReplaceService at 2026-10-18T22:22:37Z, creating checkout-00002-nt5) about 5 minutes after the service was first created with checkout-00001-ldp. Since then, every request logs 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' with timeout_ms=1, upstream=inventory, and returns 503 in about 25 ms. A 1 ms timeout is too short for any network call, so the most likely cause is a misconfigured timeout setting in the new revision, not an inventory outage. I did not compare the two revisions' env/config, and I have no logs for checkout-00001-ldp to show it worked.
**Severity:** critical  ·  **Affected:** shop-prod-4f2a/CloudRunService/checkout

**Evidence**
- `gcp_list_log_entries`: checkout-00002-nt5 stdout ERROR, repeating every ~2.5s through 22:34:31Z: 'inventory lookup failed after 1 ms: URLError: <urlopen error timed out>' with timeout_ms=1, upstream=inventory
- `gcp_list_log_entries`: Request logs for checkout-00002-nt5: GET / returns status 503 in ~0.024–0.028s
- `gcp_list_log_entries`: Audit log: google.cloud.run.v1.Services.ReplaceService on services/checkout by oncall@example.com at 2026-10-18T22:22:37Z, creating revision checkout-00002-nt5. Service had been created at 22:17:04Z with revision checkout-00001-ldp.

**Recommendations**
1. Send traffic back to the previous revision: gcloud run services update-traffic checkout --to-revisions=checkout-00001-ldp=100 --region us-central1 --project shop-prod-4f2a. This needs human approval. First check that checkout-00001-ldp served requests without errors, because I have no logs proving it was healthy.
2. Compare the env vars/config of checkout-00002-nt5 and checkout-00001-ldp to find the inventory timeout setting, likely changed from seconds or a sane ms value to 1 ms. Fix it and redeploy.
3. Ask oncall@example.com what the 22:22 change was meant to do.
4. Add validation or a minimum value for the upstream timeout setting, and add a canary or traffic-split step for checkout deploys.

**Tool calls**
1. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"checkout\" AND severity>=ERROR", "orderBy": "timestamp desc", "pageSize": 10}
2. `gcp_list_log_entries` {"resourceNames": ["projects/shop-prod-4f2a"], "filter": "logName=\"projects/shop-prod-4f2a/logs/cloudaudit.googleapis.com%2Factivity\"", "orderBy": "timestamp desc", "pageSize": 10}
3. `read_more` {"result_id": "r825bae", "grep": "methodName", "fields": ["timestamp", "protoPayload.methodName", "protoPayload.resourceName", "protoPayload.authenticationInfo.principalEmail"]}
