## About 8% of POST /charge requests are failing with 502 because payments cannot reach fraud-check at fraud-check.risk.svc.cluster.local:8443 (connection refused). The payments service is up and serving other charges normally, so the likely fault is the fraud-check dependency being down or unreachable. Fraud-check's own logs and metrics were not retrievable, so that side is unconfirmed.

**Root cause** (medium confidence, `dependency_failure`): The fraud-check risk service is refusing TCP connections on port 8443, so payments' risk check fails and it returns HTTP 502 for affected charges. Payments itself appears healthy: the other charges return 200 with normal latency. Cause on the fraud-check side (crashed pods, bad rollout, missing Service endpoints, or a network policy) is not confirmed.
**Severity:** high  ·  **Affected:** shop/Deployment/payments, risk/Deployment/fraud-check

**Evidence**
- `grafana_query_loki_logs (Loki, {service_name="payments"} |~ error/5xx pattern, last 30m)`: Repeated ERROR lines: "charge order=o-c75499fd failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused". The same error appears for orders o-2eebc721, o-7cfb5d56 and o-e022b341 in the same window. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_query_loki_patterns (Loki, {service_name="payments"}, last 30m)`: Pattern counts: "charge order=<_> status=200 latency_ms=<_>" 636 vs "charge order=<_> failed status=502: risk check unavailable ... connection refused" 135. Failures are about 17% of charges over 30m, consistent with the 8% over 10m alert.
- `grafana_query_loki_logs (Loki, {service_name="payments"} |= "status=502")`: Returned only the same mixed payments stream, not a separate 502-only result, so this is weak evidence on its own.
- `grafana_query_loki_patterns and grafana_query_loki_logs (Loki, {service_name="fraud-check"})`: Returned payments log lines and patterns instead of fraud-check data, so the fraud-check service may not be labelled service_name="fraud-check" in Loki. No fraud-check-side logs were obtained.
- `grafana_query_loki_stats (Loki, {service_name="payments"}, last 30m)`: 1 stream, 1908 entries, about 194 KB in the window, so payments log volume is active and not stalled.

**Recommendations**
1. Check fraud-check health directly: pod status, restarts, and endpoints behind the fraud-check.risk Service, and confirm it listens on 8443. Use kubectl in the risk namespace, since Loki labels did not surface its logs.
2. Check for a recent fraud-check rollout or config change that could have stopped it listening on 8443, and roll back if one lines up with the alert start time.
3. Check NetworkPolicy or Service changes in the risk namespace that could cause connection refused from the shop namespace.
4. Until fraud-check is restored, consider failing open or using a degraded risk path for charges, if the business owners approve. This is a policy decision and should not be done automatically.
5. Confirm the fraud-check dependency in Prometheus or Loki under its real service label, then re-check the payments 5xx rate to verify recovery.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_query_loki_logs`
3. `grafana_query_loki_patterns`
4. `grafana_query_loki_logs`
5. `grafana_query_loki_patterns`
6. `grafana_query_loki_logs`
7. `grafana_query_loki_logs`
8. `grafana_query_loki_stats`
9. `grafana_generate_deeplink`
