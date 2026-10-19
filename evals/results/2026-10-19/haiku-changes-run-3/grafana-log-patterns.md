## Payments POST /charge 5xx spike is caused by the payments service failing to reach fraud-check.risk.svc.cluster.local:8443, which refuses connections; each affected charge returns 502 'risk check unavailable'. Loki logs show this as the dominant error pattern (135 occurrences in the last 30m, versus 636 successful charge lines), so the fault is a fraud-check outage or unreachability, not a payments code change.

**Root cause** (medium confidence, `dependency_failure`): The fraud-check dependency at fraud-check.risk.svc.cluster.local:8443 is refusing TCP connections (connection refused). Payments fails closed and returns HTTP 502 on every charge that calls the risk check. No payments rollout or config change was seen in the data gathered, and I did not query Kubernetes or fraud-check's own health, so why fraud-check is down is still unknown.
**Severity:** high  ·  **Affected:** shop/payments (workload kind not confirmed from the data), risk/fraud-check (suspected dependency, not verified)

**Evidence**
- `grafana_query_loki_patterns (loki, {service_name="payments"}, last 30m)`: Top error pattern: 'charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' with count 135, against 636 'charge order=<_> status=200' lines.
- `grafana_query_loki_logs (loki, {service_name="payments"} |= "fraud-check", last 30m)`: Repeated ERROR lines such as 'charge order=o-2eebc721 failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused', with trace_ids attached, spread across the whole window. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_query_loki_logs (loki, {service_name="payments"} error/5xx filter, last 30m)`: Non-fraud-check lines in the same window (charge status=200 latency_ms 41-117, settlement batch queued, slow serializer 70-90ms) show no other error type, so the failure is isolated to the risk-check call.
- `grafana_list_loki_label_values (loki, service_name)`: Only 'payments' and 'storefront' services are present in Loki, so no other log source was available to confirm the fraud-check side.

**Recommendations**
1. Check whether fraud-check pods are running and whether their Service and Endpoints exist in the risk namespace (kubectl get pods,svc,endpoints -n risk); connection refused usually means no listener or no ready endpoints.
2. Check recent rollouts or changes to fraud-check and its Service port 8443 in the last hour, since payments' own code is not implicated by the logs.
3. Escalate to the fraud-check owners now, since payments is failing closed on every charge and about 8% of charge requests are returning 5xx.
4. If fraud-check cannot be restored quickly, decide with the payments owners whether to fail open for the risk check. That is a business-risk decision and should not be made by on-call alone.
5. Once fraud-check recovers, confirm the 502 rate drops back to baseline and that the 'risk check unavailable' pattern stops appearing in Loki.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_query_loki_patterns`
3. `grafana_query_loki_logs`
4. `grafana_query_loki_patterns`
5. `grafana_list_loki_label_values`
6. `grafana_query_loki_logs`
7. `grafana_generate_deeplink`
