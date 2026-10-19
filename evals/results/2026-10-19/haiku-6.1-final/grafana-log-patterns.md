## About 8% of POST /charge calls are failing with 502 because payments cannot reach fraud-check.risk.svc.cluster.local:8443 (connection refused). The payments service itself is healthy: its successful charges still return status=200. The fault is in the fraud-check dependency, which I could not inspect because no Kubernetes tools were available.

**Root cause** (medium confidence, `dependency_failure`): The fraud-check risk service at fraud-check.risk.svc.cluster.local:8443 is refusing connections (no listener, crashed, or scaled to zero), so payments' risk check fails and the charge returns 502. The payments logs show no error of its own, and no rollout is evident in the data I could query.
**Severity:** high  ·  **Affected:** shop/Deployment/payments, risk/Deployment/fraud-check (suspected, not verified)

**Evidence**
- `grafana_query_loki_patterns`: Over the last 30m, service_name="payments" logged 'charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' 135 times, against 636 successful 'charge order=<_> status=200' lines. The failure share is about 17% over the 30m window, versus the alert's 8% over 10m.
- `grafana_query_loki_logs`: Recent error lines from payments (level=error, namespace shop) repeat the same message, e.g. order o-2eebc721 and o-7cfb5d56: 'risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused'. Successful charges in the same window return status=200 with latency 41-117ms. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_query_loki_stats`: The {service_name="payments"} stream holds 1908 entries over the last 30m, in 1 stream. No separate log stream for fraud-check exists in Loki; label values are only 'payments' and 'storefront'.

**Recommendations**
1. Check the fraud-check deployment in the risk namespace: pod status, endpoints, and whether it is scaled to 0 or crashlooping. Confirm port 8443 is listening and the Service selects ready pods.
2. Check fraud-check's recent rollout history and events. If it shipped a new revision near the alert start, roll it back to the last good revision.
3. Until fraud-check recovers, consider whether payments can fail open or retry on risk-check errors, using the existing smart-retry feature flag. This needs owner approval because it changes the fraud control.
4. Confirm the 8% rate in Prometheus for POST /charge 5xx, and check whether the rate matches the 135 connection-refused failures.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_query_loki_patterns`
3. `grafana_query_loki_logs`
4. `grafana_query_loki_stats`
5. `grafana_query_loki_patterns`
6. `grafana_query_loki_stats`
7. `grafana_list_loki_label_values`
8. `grafana_query_loki_logs`
9. `grafana_generate_deeplink`
