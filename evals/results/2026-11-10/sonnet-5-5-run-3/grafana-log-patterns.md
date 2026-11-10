## About 8% of POST /charge requests in payments are failing with 502. The payments logs show the calls to the fraud-check risk service are refused: `dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused`.

**Root cause** (medium confidence, `dependency_failure`): The payments service cannot reach its fraud-check dependency at fraud-check.risk.svc.cluster.local:8443. Connections are refused, so the pod or endpoints are probably down, not ready, or not listening on that port. Charges that need a risk check return 502 and the rest succeed with status=200. I found no rollout evidence, because only Grafana log tools were available, so I could not inspect the fraud-check pods or deployment history. The cause on the fraud-check side is therefore unconfirmed.
**Severity:** high  ·  **Affected:** shop/service/payments, risk/service/fraud-check

**Evidence**
- `grafana_query_loki_patterns`: For {service_name="payments"}, the pattern 'charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused' appeared 135 times, against 636 successful status=200 charges. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)
- `grafana_query_loki_logs`: Error-level payments log lines such as 'charge order=o-c75499fd failed status=502: risk check unavailable ... connection refused' are interleaved with successful charges. This fits a partial failure of the dependency, for example some fraud-check endpoints refusing connections.

**Recommendations**
1. Check the fraud-check deployment and pods in the risk namespace for restarts, readiness failures, Pending state, or a recent rollout.
2. Check that the fraud-check service has ready endpoints and that port 8443 matches the container's listening port.
3. If a recent fraud-check rollout is found, roll it back.
4. Consider a circuit breaker or fallback in payments for when the risk check is unavailable, and add an alert on fraud-check availability.
5. Confirm recovery by watching the payments 502 rate and the 'risk check unavailable' log count fall.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_list_loki_label_names` {"datasourceUid": "loki"}
3. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "service_name"}
4. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"}"}
5. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"} |~ \"(?i)error|fail|exception|5\\d\\d\"", "limit": 30, "format": "compact"}
6. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "loki", "queries": [{"refId": "A", "expr": "{service_name=\"payments\"} |= \"risk check unavailable\""}], "timeRange": {"from": "now-1h", "to": "now"}}
