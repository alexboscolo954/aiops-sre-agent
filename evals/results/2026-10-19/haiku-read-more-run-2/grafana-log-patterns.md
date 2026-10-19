## POST /charge 5xx errors come from payments calling fraud-check.risk.svc.cluster.local:8443, which refuses connections. Payments returns 502 'risk check unavailable' on those charges, and other charges succeed with 200. The fault is in the fraud-check dependency, not in payments code, and no payments rollout is implicated in the logs.

**Root cause** (medium confidence, `dependency_failure`): Payments' risk check call to fraud-check.risk.svc.cluster.local:8443 fails with 'dial tcp ...: connect: connection refused', and payments converts that into HTTP 502 for each affected charge. The Loki pattern for this failure has 135 occurrences in the last 30 minutes, while successful charges (status=200) have 636. That is roughly 17% of charge attempts in the window, consistent with the alert's 8% over 10 minutes. Connection refused means nothing is listening on the fraud-check endpoint, which points to fraud-check being down, crashed, scaled to zero, or misrouted. I could not inspect fraud-check itself, because the only log source available was payments and storefront. Whether a recent fraud-check change caused this is unverified.
**Severity:** high  ·  **Affected:** shop/Deployment/payments, risk/Deployment/fraud-check

**Evidence**
- `grafana_list_loki_label_values`: service_name values are ["payments", "storefront"]; no separate fraud-check service stream is visible in Loki.
- `grafana_query_loki_logs`: Error lines from {service_name="payments"}: 'charge order=o-c75499fd failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' (repeated for o-e022b341, o-2eebc721, and others), interleaved with 'charge ... status=200 latency_ms=...' lines.
- `grafana_query_loki_patterns`: Over the last 30m for {service_name="payments"}: 'charge order=<_> status=200 latency_ms=<_>' totalCount 636; 'charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' totalCount 135.
- `grafana_query_loki_stats`: {service_name="payments"} over the last 30m: 1 stream, 1908 entries, 194560 bytes.
- `grafana_query_loki_patterns`: {service_name="storefront"} pattern query returned no recorded data for the window, so storefront gives no corroborating signal.

**Recommendations**
1. Check fraud-check health now: its pods, endpoints behind the risk/fraud-check Service, and whether it is crashlooping, scaled to zero, or has a bad rollout. Kubernetes tools were not available in this session, so this step is not yet done.
2. Read fraud-check's own logs and recent rollout history to see when it stopped listening on port 8443 and whether a change preceded it.
3. If fraud-check is down, restore it (roll back a bad revision, or restart or scale it up). This is the real fix. Do not restart payments as a workaround.
4. Consider a temporary degraded mode for payments (for example, bypassing or queueing the risk check) only if the business approves, since that changes fraud-screening behaviour.
5. Watch the payments 5xx ratio and the count of 'connection refused' lines drop back to zero after fraud-check recovers.

**Tool calls**
1. `grafana_list_datasources`
2. `grafana_list_loki_label_values`
3. `grafana_query_loki_logs`
4. `grafana_query_loki_patterns`
5. `grafana_query_loki_patterns`
6. `grafana_list_loki_label_values`
7. `grafana_query_loki_logs`
8. `grafana_query_loki_stats`
9. `grafana_query_loki_logs`
10. `grafana_query_loki_patterns`
11. `grafana_generate_deeplink`
12. `grafana_generate_deeplink`
13. `grafana_generate_deeplink`
14. `grafana_generate_deeplink`
