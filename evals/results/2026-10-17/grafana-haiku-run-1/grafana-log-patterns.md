## About 8% of POST /charge requests are failing with 502s because the payments service cannot reach fraud-check.risk.svc.cluster.local:8443 (connection refused). The fraud-check dependency itself is down or unreachable, and I found no logs from it to confirm why.

**Root cause** (medium confidence, `dependency_failure`): The fraud-check risk-check dependency is refusing connections on port 8443. Payments treats the risk check as mandatory, so every charge that needs it fails with status 502 instead of degrading gracefully. The fraud-check service is most likely down, crash-looping, or has a Service/endpoint or network-policy problem. Logs from the fraud-check side were not found, so this part is inferred.
**Severity:** high  ·  **Affected:** shop/Deployment/payments, risk/Deployment/fraud-check (inferred, not verified)

**Evidence**
- `grafana_query_loki_patterns (Loki, {service_name="payments"}, last 30m)`: Pattern "charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused" occurred 135 times, against 636 successful "charge ... status=200" lines (about 17% of charge outcomes over 30m).
- `grafana_query_loki_logs (Loki, {service_name="payments"} error filter, last 30m)`: Error lines are consistently ERROR-level "charge order=o-... failed status=502: risk check unavailable ... connection refused", with trace_ids attached. Successful charges with status=200 are interleaved, so the failure is partial rather than total.
- `grafana_query_loki_stats (Loki, {service_namespace="risk"}, last 1h)`: 1 stream with 1908 entries, but the service_name label values under namespace=risk returned only "payments" and "storefront". No fraud-check service logs were found, so the fraud-check side could not be inspected.

**Recommendations**
1. Check the fraud-check workload in the risk namespace: pod status, restarts, and endpoints for its Service (kubectl get pods,svc,endpoints -n risk). Confirm whether it is running and listening on 8443.
2. Read fraud-check logs and events, including previous=true for any restarting container, to find why it refuses connections.
3. Check for a recent rollout or config change to fraud-check or to the payments-to-risk network policy.
4. Confirm the 8443 address payments dials matches the fraud-check Service port. Check the payments fraud-check endpoint config for a typo or DNS change.
5. If fraud-check cannot be restored quickly, consider a payments fallback for risk-check outages (for example a degraded-accept path or a feature flag for smart-retry). This is a business decision and needs approval.
6. Watch the 5xx rate for POST /charge in Prometheus to confirm recovery after the fix.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_query_loki_patterns`
3. `grafana_query_loki_logs`
4. `grafana_query_loki_patterns`
5. `grafana_query_loki_logs`
6. `grafana_query_loki_label_values`
7. `grafana_query_loki_stats`
8. `grafana_list_loki_label_values`
9. `grafana_list_loki_label_values`
10. `grafana_query_loki_logs`
