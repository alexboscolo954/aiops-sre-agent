## About 8% of POST /charge requests are failing with 502s because payments cannot reach the fraud-check risk service at fraud-check.risk.svc.cluster.local:8443, which returns connection refused. The root cause sits in fraud-check or its networking, not in payments code.

**Root cause** (medium confidence, `dependency_failure`): The fraud-check dependency in the risk namespace is refusing TCP connections on port 8443 (down, crashed, scaled to zero, or its Service has no ready endpoints). Payments fails closed and returns 502 on every charge that needs a risk check. Loki shows no logs from fraud-check itself, so the dependency's own health is unconfirmed.
**Severity:** high  ·  **Affected:** shop/Deployment/payments, risk/Deployment/fraud-check

**Evidence**
- `grafana_query_loki_patterns {service_name="payments"} (last 30m)`: Pattern 'charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' occurs 135 times, against 636 successful 'charge ... status=200' lines in the same window (roughly 17% of charge outcomes in the window).
- `grafana_query_loki_logs {service_name="payments"} |~ error/5xx (last 30m)`: Error lines are consistently 'charge order=o-... failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' with ERROR level, interleaved with normal 200 charges. The failure is continuous, not a single burst.
- `grafana_list_loki_label_values service_name (namespaces set)`: Only 'payments' and 'storefront' emit logs with service_namespace set. No fraud-check or risk service logs appear in Loki for the last hour, so its health could not be checked from logs.
- `grafana_query_loki_stats {service_name="fraud-check"} (last 1h)`: Returned 1 stream, 1908 entries, 194560 bytes. These are identical to the payments stats, so the result may be a selector artifact and not evidence of fraud-check activity.
- `grafana_generate_deeplink (explore, Loki)`: Explore link to payments logs for the last 30m. The generated expression is payments-only, so it does not filter to fraud-check failures. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)

**Recommendations**
1. Check the fraud-check workload in the risk namespace: pod status, restarts, recent events, and whether the Service has ready endpoints (kubectl get pods,svc,endpoints -n risk). The tools here did not expose Kubernetes state, so this is unverified.
2. Read fraud-check's own logs (current and previous container) to find why it stopped accepting connections on 8443, and check for a recent rollout or config change to it.
3. If fraud-check is down, restore it first (rollback, restart, or scale up). Restarts and scaling need human approval.
4. Only if fraud-check cannot be restored soon, decide with the payments owners whether to fail open on risk-check outage. That is a business and fraud-risk decision, not a default change.
5. Once fraud-check is healthy, confirm the 502 count drops to zero in Loki and that the payments error rate falls below the alert threshold.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_query_loki_patterns`
3. `grafana_query_loki_logs`
4. `grafana_query_loki_stats`
5. `grafana_query_loki_logs`
6. `grafana_query_loki_logs`
7. `grafana_query_loki_patterns`
8. `grafana_list_loki_label_values`
9. `grafana_query_loki_stats`
10. `grafana_query_loki_logs`
11. `grafana_generate_deeplink`
