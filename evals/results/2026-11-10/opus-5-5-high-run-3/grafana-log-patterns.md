## Payments (namespace shop) returns 502 on POST /charge because it can't reach its fraud-check dependency: calls to fraud-check.risk.svc.cluster.local:8443 fail with 'connection refused'. Other charges succeed, so the dependency is failing intermittently or only on some endpoints. Payments itself looks healthy.

**Root cause** (medium confidence, `dependency_failure`): Every failed charge in the payments logs reads 'failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused'. That pattern appears 135 times in the last hour, against 636 'charge ... status=200'. 'Connection refused' means the fraud-check Service address answered but nothing accepted connections on port 8443. Likely causes are fraud-check pods that are down, restarting or not ready, with some endpoints still listed, or a wrong port. Loki has no fraud-check logs (only payments and storefront send logs), and I had no Kubernetes or Prometheus tools, so I couldn't check fraud-check's state or recent rollouts. I can't tell whether this is a bad fraud-check rollout or another failure.
**Severity:** high  ·  **Affected:** shop/Deployment/payments, risk/Service/fraud-check

**Evidence**
- `grafana_query_loki_patterns`: Last hour of {service_name="payments"}: 'charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' x135 vs 'charge order=<_> status=200' x636; no other error pattern. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_query_loki_logs`: Raw payments logs (service_namespace=shop) show 502 errors at ERROR level, e.g. order o-c75499fd and o-e022b341 (trace fb954a35bf708d397bd3ca19b85ee09a), mixed in with successful 200 charges.
- `grafana_list_loki_label_values`: Only 'payments' and 'storefront' send logs to Loki, so fraud-check's own logs couldn't be checked here.

**Recommendations**
1. Check fraud-check in the risk namespace: run `kubectl -n risk get pods,endpoints fraud-check` and look for CrashLoopBackOff, not-ready pods or recent restarts.
2. Run `kubectl -n risk rollout history deploy/fraud-check` and read the recent events. If a new revision went out just before the errors began, roll it back.
3. Check that the fraud-check Service's targetPort matches the port the container listens on (8443) and that readiness probes take bad pods out of the endpoints.
4. Read the logs of any failing fraud-check pod, using --previous for crashed containers, to find why it refuses connections.
5. Once fraud-check is healthy, confirm the payments 502 rate falls with the payments Loki query linked above. Then consider a circuit breaker or fallback for risk-check outages in payments.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"}"}
3. `grafana_query_loki_stats` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"}"}
4. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "service_name"}
5. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"} |= \"status=502\"", "direction": "forward", "limit": 5}
6. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "loki", "queries": [{"refId": "A", "expr": "{service_name=\"payments\"} |= \"risk check unavailable\""}], "timeRange": {"from": "now-1h", "to": "now"}}
