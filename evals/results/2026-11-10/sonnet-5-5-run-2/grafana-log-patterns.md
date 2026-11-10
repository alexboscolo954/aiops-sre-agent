## About 8% of POST /charge requests in payments are returning 502. The payments logs show the calls failing because fraud-check.risk.svc.cluster.local:8443 refuses connections.

**Root cause** (medium confidence, `dependency_failure`): The payments service calls its risk check dependency at fraud-check.risk.svc.cluster.local:8443, and the connection is refused. Payments turns each refusal into a 502 ("risk check unavailable"). The refusals are intermittent, since successful status=200 charges are interleaved with the failures. That fits a fraud-check service that is partly down, such as some endpoints not ready, restarting, or not listening. I only had Loki, so I could not check fraud-check's pods, its rollout history or any Prometheus metrics. I found no sign of a payments-side change. The cause on the fraud-check side is unconfirmed.
**Severity:** high  ·  **Affected:** shop/Service/payments, risk/Service/fraud-check

**Evidence**
- `grafana_query_loki_patterns`: The payments logs have 135 lines matching "charge order=<_> failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused". 636 lines show successful charges with status=200. No other error pattern is prominent.
- `grafana_query_loki_logs`: ERROR lines such as "charge order=o-c75499fd failed status=502: risk check unavailable: dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused" appear between successful status=200 charges. This shows intermittent connection refusals to fraud-check. (http://localhost:3000/explore?panes=%7B%22a%22%3A%7B%22datasource%22%3A%22loki%22%2C%22queries%22%3A%5B%7B%22datasource%22%3A%7B%22uid%22%3A%22loki%22%7D%2C%22expr%22%3A%22%7Bservice_name%3D%5C%22payments%5C%22%7D%22%2C%22refId%22%3A%22A%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%7D%7D%7D&schemaVersion=1)

**Recommendations**
1. Check the fraud-check service in the risk namespace: pod readiness and restarts, endpoints, and whether anything is listening on port 8443.
2. Check fraud-check's recent rollout history and revert it if a new revision lines up with the start of the errors.
3. Check the Service selector and port 8443 for fraud-check, and any NetworkPolicy that affects traffic from the shop namespace.
4. If fraud-check cannot be restored quickly, consider a fail-open or retry fallback in payments, if policy allows. The smart-retry flag is already on.
5. Add an alert on fraud-check availability so this is caught at the source.

**Tool calls**
1. `grafana_list_datasources` {}
2. `grafana_list_loki_label_names` {"datasourceUid": "loki"}
3. `grafana_list_loki_label_values` {"datasourceUid": "loki", "labelName": "service_name"}
4. `grafana_query_loki_patterns` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"}"}
5. `grafana_query_loki_logs` {"datasourceUid": "loki", "logql": "{service_name=\"payments\"} |~ \"(?i)error|fail|exception|5\\\\d\\\\d\"", "limit": 30, "format": "compact"}
6. `grafana_generate_deeplink` {"resourceType": "explore", "datasourceUid": "loki", "queries": [{"refId": "A", "expr": "{service_name=\"payments\"} |= \"risk check unavailable\""}], "timeRange": {"from": "now-1h", "to": "now"}}
