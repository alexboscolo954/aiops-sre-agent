## The payments POST /charge 5xx spike is caused by the payments service failing to reach the fraud-check dependency at fraud-check.risk.svc.cluster.local:8443 ("connection refused"). Those calls return 502 and account for the errors; other charge requests succeed with status 200. I did not find a rollout or config change in this investigation, and I could not check the fraud-check pods, so the fraud-check outage is inferred from the connection-refused errors.

**Root cause** (medium confidence, `dependency_failure`): The payments service calls fraud-check over the risk check. The fraud-check endpoint refuses connections, so each affected charge fails with 502: "risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused". Loki shows this as the second most common pattern for payments (135 occurrences in the queried window). The other charge lines are status=200. This points to the fraud-check service being down or not listening on 8443, not to a payments code fault. The alert's 8% 5xx rate matches a fraction of charges failing this way. I did not confirm the exact share or the start time in Prometheus.
**Severity:** high  ·  **Affected:** shop/Deployment/payments, risk/Deployment/fraud-check (inferred dependency, not inspected)

**Evidence**
- `grafana_query_loki_patterns`: Pattern for {service_name="payments"}: "charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused" appears 135 times; the most common charge pattern is status=200 (636).
- `grafana_query_loki_logs`: Recent payments error lines (service_namespace=shop, level=error) e.g. 'charge order=o-c75499fd failed status=502: risk check unavailable ... connect: connection refused', interleaved with 'charge order=o-aa4aea67 status=200 latency_ms=85'.
- `grafana_query_loki_stats`: {service_name="payments"} has 1 stream and 1908 entries in the last hour.
- `grafana_generate_deeplink`: Explore link for the payments 'risk check unavailable' query in Loki. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)

**Recommendations**
1. Check the fraud-check workload in the risk namespace: pod status, restarts, endpoints, and Service port 8443. Confirm whether it is down or was moved or changed.
2. Check for a recent rollout or config change to fraud-check or its Service/NetworkPolicy, and roll back if one lines up with the start of the errors.
3. Check the payments dependency handling. Consider a timeout, fallback, or circuit breaker for the risk check, depending on policy, so charges do not fail hard when fraud-check is down.
4. Confirm the 5xx ratio and start time in Prometheus and compare it with the alert window.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_list_loki_label_values` {"datasourceUid": "default", "labelName": "namespace"} (error)
3. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "namespace"}
4. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"}"}
5. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"} |= \"risk check unavailable\"", "limit": 5}
6. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{namespace=\"risk\"} |~ \"(?i)error|refused|crash|panic\"", "limit": 10}
7. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=~\".*fraud.*\"} or {namespace=\"risk\"}", "limit": 10}
8. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "service_name"}
9. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "namespace", "matcher": "{service_name=\"payments\"}"}
10. `grafana_query_loki_stats` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"}"}
11. `grafana_list_loki_label_values` {"datasourceUid": "prometheus", "labelName": "namespace"} (error)
12. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "loki", "queries": [{"refId": "A", "expr": "{service_name=\"payments\"} |= \"risk check unavailable\""}]}
13. `TriageReport` {"summary": "The payments POST /charge 5xx spike is caused by the payments service failing to reach the fraud-check dependency at fraud-check.risk.svc.cluster.local:8443 (\"connection refused\"). Those calls return 502 and account for the errors; other charge requests succeed with status 200. I did 
