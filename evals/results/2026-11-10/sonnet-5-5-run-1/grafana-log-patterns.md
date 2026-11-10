## Payments POST /charge is returning 502s because its call to the fraud-check service (risk namespace, port 8443) is refused. Charges that don't hit that failure still return 200.

**Root cause** (medium confidence, `dependency_failure`): The payments service calls fraud-check.risk.svc.cluster.local:8443 for its risk check, and the connection is refused. The log line is "charge order=... failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused". It is the second most frequent log pattern, with 135 occurrences against 636 successful charges, which is roughly in line with the alerted 8% error rate. Connection refused means the fraud-check pods are down, have no ready endpoints, or are not listening on 8443. I did not check the fraud-check deployment, its rollout history, or any rollout timing, because only the payments and storefront logs were available to me. I found no payments-side errors such as crashes or OOM kills.
**Severity:** medium  ·  **Affected:** shop/service/payments, risk/service/fraud-check

**Evidence**
- `grafana_query_loki_patterns`: Payments log pattern "charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused" appears 135 times, against 636 for the successful "status=200" charge pattern. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_query_loki_logs`: Raw ERROR lines from payments (namespace shop) show intermittent 502s with "risk check unavailable ... connection refused" mixed in with 200 responses. Each carries a trace_id.

**Recommendations**
1. Check the fraud-check deployment and pods in the risk namespace for readiness, restarts and endpoints (kubectl -n risk get pods,endpoints fraud-check).
2. Check fraud-check's rollout history and recent changes, and confirm it is listening on port 8443 and that the Service targetPort is correct.
3. Check for a NetworkPolicy blocking traffic from shop to risk.
4. If a recent fraud-check rollout caused this, roll it back or restore the pods.
5. Consider a timeout, retry or circuit breaker in payments for fraud-check failures, or a fail-open policy if the business allows it.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_list_loki_label_names` {"datasourceUid": "loki"}
3. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "service_name"}
4. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"}"}
5. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"} |~ \"(?i)error|fail|exception|5\\\\d\\\\d\"", "limit": 30, "format": "compact"}
6. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "loki", "queries": [{"refId": "A", "expr": "{service_name=\"payments\"} |= \"risk check unavailable\""}], "timeRange": {"from": "now-1h", "to": "now"}}
